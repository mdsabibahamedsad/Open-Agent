import pytest
import pytest_asyncio
import asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from openagent.main import app
from openagent.db.session import Base, init_db, close_db, get_db
from openagent.db.models import (
    User, UserStatus,
    Organization, OrganizationStatus,
    Membership, MembershipRole, MembershipStatus,
    Session, ApiKey,
    Agent, AgentVersion, Workflow, WorkflowVersion, WorkflowExecution,
    Task, AgentRun, ExecutionEvent, Tool, Credential, Integration,
    MCPServer, Memory, Conversation, Message, Approval, Evaluation,
    AuditLog, Webhook,
)
from openagent.core.config import get_settings


# Test database URL - use the application's database URL
# In CI/CD, this should point to a PostgreSQL test database
TEST_DATABASE_URL = get_settings().DATABASE_URL


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    connect_args = {}
    poolclass = None
    
    if TEST_DATABASE_URL.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        poolclass = StaticPool
    
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=poolclass,
        connect_args=connect_args,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncSession:
    async_session_maker = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    # Override the get_db dependency
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()


# Database model fixtures
@pytest_asyncio.fixture
async def org_a(db_session: AsyncSession) -> Organization:
    org = Organization(
        name="Organization A",
        slug="org-a-test",
        status=OrganizationStatus.ACTIVE
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def org_b(db_session: AsyncSession) -> Organization:
    org = Organization(
        name="Organization B",
        slug="org-b-test",
        status=OrganizationStatus.ACTIVE
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    user = User(
        email="user-a-test@example.com",
        display_name="User A",
        status=UserStatus.ACTIVE
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    user = User(
        email="user-b-test@example.com",
        display_name="User B",
        status=UserStatus.ACTIVE
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def membership_a(db_session: AsyncSession, user_a: User, org_a: Organization) -> Membership:
    membership = Membership(
        user_id=user_a.id,
        organization_id=org_a.id,
        role=MembershipRole.OWNER,
        status=MembershipStatus.ACTIVE
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(membership)
    return membership


@pytest_asyncio.fixture
async def membership_b(db_session: AsyncSession, user_b: User, org_b: Organization) -> Membership:
    membership = Membership(
        user_id=user_b.id,
        organization_id=org_b.id,
        role=MembershipRole.OWNER,
        status=MembershipStatus.ACTIVE
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(membership)
    return membership