import pytest
import pytest_asyncio
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.models import (
    User, UserStatus,
    Organization, OrganizationStatus,
    Agent, AgentType, AgentStatus,
)
from openagent.db.repositories import (
    UserRepository,
    OrganizationRepository,
    AgentRepository,
)
from openagent.db.pagination import (
    PaginationParams,
    create_pagination_meta,
    create_cursor_pagination_meta,
    paginate_query,
)


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> Organization:
    repo = OrganizationRepository(db_session)
    org = await repo.create(
        name="Test Org",
        slug="test-org-pagination",
        status=OrganizationStatus.ACTIVE
    )
    await db_session.commit()
    return org


@pytest_asyncio.fixture
async def users(db_session: AsyncSession) -> list[User]:
    repo = UserRepository(db_session)
    users = []
    for i in range(25):
        user = await repo.create(
            email=f"user{i}@example.com",
            display_name=f"User {i}",
            status=UserStatus.ACTIVE
        )
        users.append(user)
    await db_session.commit()
    return users


class TestPagination:
    def test_pagination_meta_creation(self):
        meta = create_pagination_meta(page=1, page_size=20, total_items=100)
        assert meta.page == 1
        assert meta.page_size == 20
        assert meta.total_items == 100
        assert meta.total_pages == 5
        assert meta.has_next is True
        assert meta.has_prev is False

    def test_pagination_meta_last_page(self):
        meta = create_pagination_meta(page=5, page_size=20, total_items=100)
        assert meta.page == 5
        assert meta.has_next is False
        assert meta.has_prev is True

    def test_pagination_meta_single_page(self):
        meta = create_pagination_meta(page=1, page_size=20, total_items=10)
        assert meta.total_pages == 1
        assert meta.has_next is False
        assert meta.has_prev is False

    def test_cursor_pagination_meta(self):
        class MockItem:
            def __init__(self, id):
                self.id = id
        
        items = [MockItem(i) for i in range(25)]
        meta = create_cursor_pagination_meta(items, limit=20)
        
        assert meta.has_next is True
        assert meta.next_cursor == "19"
        assert meta.limit == 20

    def test_cursor_pagination_meta_no_next(self):
        class MockItem:
            def __init__(self, id):
                self.id = id
        
        items = [MockItem(i) for i in range(10)]
        meta = create_cursor_pagination_meta(items, limit=20)
        
        assert meta.has_next is False
        assert meta.next_cursor is None


class TestOffsetPagination:
    async def test_first_page(self, db_session: AsyncSession, users: list[User]):
        repo = UserRepository(db_session)
        pagination = PaginationParams(page=1, page_size=10)
        
        results = await repo.list(limit=pagination.page_size, offset=(pagination.page - 1) * pagination.page_size)
        
        assert len(results) == 10

    async def test_second_page(self, db_session: AsyncSession, users: list[User]):
        repo = UserRepository(db_session)
        pagination = PaginationParams(page=2, page_size=10)
        
        results = await repo.list(limit=pagination.page_size, offset=(pagination.page - 1) * pagination.page_size)
        
        assert len(results) == 10

    async def test_last_page(self, db_session: AsyncSession, users: list[User]):
        repo = UserRepository(db_session)
        pagination = PaginationParams(page=3, page_size=10)
        
        results = await repo.list(limit=pagination.page_size, offset=(pagination.page - 1) * pagination.page_size)
        
        assert len(results) == 5  # 25 total - 20 = 5

    async def test_page_beyond_total(self, db_session: AsyncSession, users: list[User]):
        repo = UserRepository(db_session)
        pagination = PaginationParams(page=10, page_size=10)
        
        results = await repo.list(limit=pagination.page_size, offset=(pagination.page - 1) * pagination.page_size)
        
        assert len(results) == 0

    async def test_deterministic_ordering(self, db_session: AsyncSession, users: list[User]):
        repo = UserRepository(db_session)
        
        page1 = await repo.list(limit=10, offset=0, order_by="created_at", order_desc=True)
        page1_again = await repo.list(limit=10, offset=0, order_by="created_at", order_desc=True)
        
        # Same page should return same results in same order
        assert [u.id for u in page1] == [u.id for u in page1_again]

    async def test_organization_scoped_pagination(self, db_session: AsyncSession, org: Organization):
        agent_repo = AgentRepository(db_session)
        
        # Create 15 agents in the org
        for i in range(15):
            await agent_repo.create(
                organization_id=org.id,
                name=f"Agent {i}",
                slug=f"agent-{i}",
                status=AgentStatus.ACTIVE,
                agent_type=AgentType.CHAT
            )
        await db_session.commit()
        
        page1 = await agent_repo.list(organization_id=org.id, limit=10, offset=0)
        page2 = await agent_repo.list(organization_id=org.id, limit=10, offset=10)
        
        assert len(page1) == 10
        assert len(page2) == 5
        
        # Verify no overlap
        page1_ids = {a.id for a in page1}
        page2_ids = {a.id for a in page2}
        assert page1_ids.isdisjoint(page2_ids)