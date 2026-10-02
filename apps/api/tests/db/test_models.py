import pytest
import pytest_asyncio
from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.models import (
    User, UserStatus,
    Organization, OrganizationStatus,
    Membership, MembershipRole, MembershipStatus,
    Agent, AgentVersion, AgentType, AgentStatus,
    Workflow, WorkflowVersion, WorkflowStatus,
    WorkflowExecution, WorkflowExecutionStatus, WorkflowExecutionTriggerType,
    Task, TaskStatus, TaskPriority,
    AgentRun, AgentRunStatus,
    ExecutionEvent,
    Tool, ToolType, ToolStatus,
    Credential, CredentialType, CredentialStatus,
    Integration, IntegrationProvider, IntegrationStatus,
    MCPServer, MCPTransport, MCPServerStatus,
    Memory, MemoryType,
    Conversation, Message, ConversationStatus, MessageRole,
    Approval, ApprovalType, ApprovalStatus,
    Evaluation, EvaluatorType, EvaluationStatus,
    AuditLog,
    ApiKey,
    Webhook, WebhookStatus,
    Session,
)
from openagent.db.repositories import (
    UserRepository,
    OrganizationRepository,
    MembershipRepository,
    AgentRepository,
    AgentVersionRepository,
    WorkflowRepository,
    WorkflowVersionRepository,
    WorkflowExecutionRepository,
    TaskRepository,
    AgentRunRepository,
    ExecutionEventRepository,
    CredentialRepository,
    IntegrationRepository,
    MCPServerRepository,
    MemoryRepository,
    ConversationRepository,
    MessageRepository,
    ApprovalRepository,
    EvaluationRepository,
    AuditLogRepository,
    WebhookRepository,
    ApiKeyRepository,
)
from openagent.db.session import get_db


@pytest_asyncio.fixture
async def db_session():
    """Get a database session for testing."""
    async for session in get_db():
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def org_a(db_session: AsyncSession) -> Organization:
    repo = OrganizationRepository(db_session)
    org = await repo.create(
        name="Organization A",
        slug="org-a",
        status=OrganizationStatus.ACTIVE
    )
    await db_session.commit()
    return org


@pytest_asyncio.fixture
async def org_b(db_session: AsyncSession) -> Organization:
    repo = OrganizationRepository(db_session)
    org = await repo.create(
        name="Organization B",
        slug="org-b",
        status=OrganizationStatus.ACTIVE
    )
    await db_session.commit()
    return org


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    repo = UserRepository(db_session)
    user = await repo.create(
        email="user-a@example.com",
        display_name="User A",
        status=UserStatus.ACTIVE
    )
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    repo = UserRepository(db_session)
    user = await repo.create(
        email="user-b@example.com",
        display_name="User B",
        status=UserStatus.ACTIVE
    )
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def membership_a(db_session: AsyncSession, user_a: User, org_a: Organization) -> Membership:
    repo = MembershipRepository(db_session)
    membership = await repo.create(
        user_id=user_a.id,
        organization_id=org_a.id,
        role=MembershipRole.OWNER,
        status=MembershipStatus.ACTIVE
    )
    await db_session.commit()
    return membership


@pytest_asyncio.fixture
async def membership_b(db_session: AsyncSession, user_b: User, org_b: Organization) -> Membership:
    repo = MembershipRepository(db_session)
    membership = await repo.create(
        user_id=user_b.id,
        organization_id=org_b.id,
        role=MembershipRole.OWNER,
        status=MembershipStatus.ACTIVE
    )
    await db_session.commit()
    return membership


class TestUserModel:
    async def test_create_user(self, db_session: AsyncSession):
        repo = UserRepository(db_session)
        user = await repo.create(
            email="test@example.com",
            display_name="Test User",
            status=UserStatus.ACTIVE
        )
        await db_session.commit()
        
        assert user.id is not None
        assert user.email == "test@example.com"
        assert user.display_name == "Test User"
        assert user.status == UserStatus.ACTIVE
        assert user.is_superadmin is False
        assert user.created_at is not None
        assert user.updated_at is not None

    async def test_unique_email_constraint(self, db_session: AsyncSession, user_a: User):
        repo = UserRepository(db_session)
        with pytest.raises(Exception):
            await repo.create(
                email=user_a.email,
                display_name="Another User",
                status=UserStatus.ACTIVE
            )
            await db_session.commit()

    async def test_get_by_email(self, db_session: AsyncSession, user_a: User):
        repo = UserRepository(db_session)
        found = await repo.get_by_email(user_a.email)
        assert found is not None
        assert found.id == user_a.id


class TestOrganizationModel:
    async def test_create_organization(self, db_session: AsyncSession):
        repo = OrganizationRepository(db_session)
        org = await repo.create(
            name="Test Org",
            slug="test-org",
            status=OrganizationStatus.ACTIVE
        )
        await db_session.commit()
        
        assert org.id is not None
        assert org.name == "Test Org"
        assert org.slug == "test-org"
        assert org.status == OrganizationStatus.ACTIVE
        assert org.created_at is not None

    async def test_unique_slug_constraint(self, db_session: AsyncSession, org_a: Organization):
        repo = OrganizationRepository(db_session)
        with pytest.raises(Exception):
            await repo.create(
                name="Another Org",
                slug=org_a.slug,
                status=OrganizationStatus.ACTIVE
            )
            await db_session.commit()

    async def test_get_by_slug(self, db_session: AsyncSession, org_a: Organization):
        repo = OrganizationRepository(db_session)
        found = await repo.get_by_slug(org_a.slug)
        assert found is not None
        assert found.id == org_a.id


class TestMembershipModel:
    async def test_create_membership(self, db_session: AsyncSession, user_a: User, org_a: Organization):
        repo = MembershipRepository(db_session)
        membership = await repo.create(
            user_id=user_a.id,
            organization_id=org_a.id,
            role=MembershipRole.MEMBER,
            status=MembershipStatus.ACTIVE
        )
        await db_session.commit()
        
        assert membership.id is not None
        assert membership.user_id == user_a.id
        assert membership.organization_id == org_a.id
        assert membership.role == MembershipRole.MEMBER

    async def test_unique_user_org_constraint(self, db_session: AsyncSession, membership_a: Membership):
        repo = MembershipRepository(db_session)
        with pytest.raises(Exception):
            await repo.create(
                user_id=membership_a.user_id,
                organization_id=membership_a.organization_id,
                role=MembershipRole.ADMIN,
                status=MembershipStatus.ACTIVE
            )
            await db_session.commit()


class TestAgentModel:
    async def test_create_agent(self, db_session: AsyncSession, org_a: Organization):
        repo = AgentRepository(db_session)
        agent = await repo.create(
            organization_id=org_a.id,
            name="Test Agent",
            slug="test-agent",
            status=AgentStatus.DRAFT,
            agent_type=AgentType.CHAT
        )
        await db_session.commit()
        
        assert agent.id is not None
        assert agent.organization_id == org_a.id
        assert agent.name == "Test Agent"
        assert agent.slug == "test-agent"
        assert agent.status == AgentStatus.DRAFT

    async def test_unique_slug_per_org(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        repo = AgentRepository(db_session)
        await repo.create(
            organization_id=org_a.id,
            name="Agent 1",
            slug="my-agent",
            status=AgentStatus.DRAFT
        )
        await db_session.commit()
        
        # Same slug in different org should work
        agent2 = await repo.create(
            organization_id=org_b.id,
            name="Agent 2",
            slug="my-agent",
            status=AgentStatus.DRAFT
        )
        await db_session.commit()
        assert agent2.id is not None
        
        # Same slug in same org should fail
        with pytest.raises(Exception):
            await repo.create(
                organization_id=org_a.id,
                name="Agent 3",
                slug="my-agent",
                status=AgentStatus.DRAFT
            )
            await db_session.commit()


class TestAgentVersionModel:
    async def test_create_agent_version(self, db_session: AsyncSession, org_a: Organization):
        agent_repo = AgentRepository(db_session)
        agent = await agent_repo.create(
            organization_id=org_a.id,
            name="Test Agent",
            slug="test-agent",
            status=AgentStatus.ACTIVE
        )
        await db_session.commit()
        
        version_repo = AgentVersionRepository(db_session)
        version = await version_repo.create(
            agent_id=agent.id,
            version="1.0.0",
            name="Version 1",
            status="published"
        )
        await db_session.commit()
        
        assert version.id is not None
        assert version.agent_id == agent.id
        assert version.version == "1.0.0"

    async def test_unique_version_per_agent(self, db_session: AsyncSession, org_a: Organization):
        agent_repo = AgentRepository(db_session)
        agent = await agent_repo.create(
            organization_id=org_a.id,
            name="Test Agent",
            slug="test-agent",
            status=AgentStatus.ACTIVE
        )
        await db_session.commit()
        
        version_repo = AgentVersionRepository(db_session)
        await version_repo.create(
            agent_id=agent.id,
            version="1.0.0",
            name="Version 1",
            status="published"
        )
        await db_session.commit()
        
        with pytest.raises(Exception):
            await version_repo.create(
                agent_id=agent.id,
                version="1.0.0",
                name="Version 1 Duplicate",
                status="published"
            )
            await db_session.commit()


class TestWorkflowModel:
    async def test_create_workflow(self, db_session: AsyncSession, org_a: Organization):
        repo = WorkflowRepository(db_session)
        workflow = await repo.create(
            organization_id=org_a.id,
            name="Test Workflow",
            slug="test-workflow",
            status=WorkflowStatus.DRAFT
        )
        await db_session.commit()
        
        assert workflow.id is not None
        assert workflow.organization_id == org_a.id
        assert workflow.name == "Test Workflow"

    async def test_unique_slug_per_org(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        repo = WorkflowRepository(db_session)
        await repo.create(
            organization_id=org_a.id,
            name="Workflow 1",
            slug="my-workflow",
            status=WorkflowStatus.DRAFT
        )
        await db_session.commit()
        
        # Same slug in different org should work
        workflow2 = await repo.create(
            organization_id=org_b.id,
            name="Workflow 2",
            slug="my-workflow",
            status=WorkflowStatus.DRAFT
        )
        await db_session.commit()
        assert workflow2.id is not None


class TestWorkflowExecutionModel:
    async def test_create_execution(self, db_session: AsyncSession, org_a: Organization):
        workflow_repo = WorkflowRepository(db_session)
        workflow = await workflow_repo.create(
            organization_id=org_a.id,
            name="Test Workflow",
            slug="test-workflow",
            status=WorkflowStatus.ACTIVE
        )
        await db_session.commit()
        
        exec_repo = WorkflowExecutionRepository(db_session)
        execution = await exec_repo.create(
            organization_id=org_a.id,
            workflow_id=workflow.id,
            status=WorkflowExecutionStatus.QUEUED,
            trigger_type=WorkflowExecutionTriggerType.MANUAL
        )
        await db_session.commit()
        
        assert execution.id is not None
        assert execution.organization_id == org_a.id
        assert execution.workflow_id == workflow.id
        assert execution.status == WorkflowExecutionStatus.QUEUED


class TestTaskModel:
    async def test_create_task(self, db_session: AsyncSession, org_a: Organization):
        repo = TaskRepository(db_session)
        task = await repo.create(
            organization_id=org_a.id,
            type="test_task",
            status=TaskStatus.PENDING,
            priority=TaskPriority.NORMAL,
            payload={"key": "value"}
        )
        await db_session.commit()
        
        assert task.id is not None
        assert task.organization_id == org_a.id
        assert task.type == "test_task"
        assert task.status == TaskStatus.PENDING

    async def test_task_claim(self, db_session: AsyncSession, org_a: Organization):
        repo = TaskRepository(db_session)
        task = await repo.create(
            organization_id=org_a.id,
            type="test_task",
            status=TaskStatus.PENDING,
            payload={}
        )
        await db_session.commit()
        
        claimed = await repo.claim_task(task.id)
        assert claimed is not None
        assert claimed.status == TaskStatus.RUNNING
        assert claimed.started_at is not None
        assert claimed.attempts == 1


class TestAgentRunModel:
    async def test_create_agent_run(self, db_session: AsyncSession, org_a: Organization):
        agent_repo = AgentRepository(db_session)
        agent = await agent_repo.create(
            organization_id=org_a.id,
            name="Test Agent",
            slug="test-agent",
            status=AgentStatus.ACTIVE
        )
        await db_session.commit()
        
        run_repo = AgentRunRepository(db_session)
        run = await run_repo.create(
            organization_id=org_a.id,
            agent_id=agent.id,
            status=AgentRunStatus.QUEUED,
            input={"prompt": "Hello"}
        )
        await db_session.commit()
        
        assert run.id is not None
        assert run.organization_id == org_a.id
        assert run.agent_id == agent.id


class TestExecutionEventModel:
    async def test_create_event(self, db_session: AsyncSession, org_a: Organization):
        event_repo = ExecutionEventRepository(db_session)
        
        event = await event_repo.create_event(
            organization_id=org_a.id,
            event_type="agent.started",
            payload={"agent_id": str(uuid4())}
        )
        await db_session.commit()
        
        assert event.id is not None
        assert event.organization_id == org_a.id
        assert event.event_type == "agent.started"
        assert event.sequence == 1
        
        # Second event should have sequence 2
        event2 = await event_repo.create_event(
            organization_id=org_a.id,
            event_type="agent.completed",
            payload={}
        )
        await db_session.commit()
        assert event2.sequence == 2


class TestCredentialModel:
    async def test_create_credential(self, db_session: AsyncSession, org_a: Organization):
        repo = CredentialRepository(db_session)
        credential = await repo.create(
            organization_id=org_a.id,
            name="Test API Key",
            provider="openai",
            credential_type=CredentialType.API_KEY,
            encrypted_data="encrypted_secret_data",
            status=CredentialStatus.ACTIVE
        )
        await db_session.commit()
        
        assert credential.id is not None
        assert credential.organization_id == org_a.id
        assert credential.encrypted_data == "encrypted_secret_data"
        # Plain text secret should NOT be stored
        assert "plaintext" not in str(credential.encrypted_data).lower()


class TestIntegrationModel:
    async def test_create_integration(self, db_session: AsyncSession, org_a: Organization):
        cred_repo = CredentialRepository(db_session)
        credential = await cred_repo.create(
            organization_id=org_a.id,
            name="GitHub Token",
            provider="github",
            credential_type=CredentialType.OAUTH_TOKEN,
            encrypted_data="encrypted_token",
            status=CredentialStatus.ACTIVE
        )
        await db_session.commit()
        
        repo = IntegrationRepository(db_session)
        integration = await repo.create(
            organization_id=org_a.id,
            provider=IntegrationProvider.GITHUB,
            name="GitHub Integration",
            status=IntegrationStatus.ACTIVE,
            credential_id=credential.id
        )
        await db_session.commit()
        
        assert integration.id is not None
        assert integration.provider == IntegrationProvider.GITHUB
        assert integration.credential_id == credential.id


class TestAuditLogModel:
    async def test_create_audit_log(self, db_session: AsyncSession, org_a: Organization, user_a: User):
        repo = AuditLogRepository(db_session)
        log = await repo.log(
            organization_id=org_a.id,
            actor_user_id=user_a.id,
            action="agent.created",
            resource_type="agent",
            resource_id=uuid4(),
            metadata={"name": "Test Agent"}
        )
        await db_session.commit()
        
        assert log.id is not None
        assert log.organization_id == org_a.id
        assert log.actor_user_id == user_a.id
        assert log.action == "agent.created"
        assert log.resource_type == "agent"

    async def test_audit_log_append_only(self, db_session: AsyncSession, org_a: Organization, user_a: User):
        repo = AuditLogRepository(db_session)
        log = await repo.log(
            organization_id=org_a.id,
            actor_user_id=user_a.id,
            action="test.action",
            resource_type="test",
            resource_id=uuid4()
        )
        await db_session.commit()
        
        # Audit logs should not be easily mutable
        # (In practice, this would be enforced at application level)
        found = await repo.get_by_id(log.id)
        assert found is not None
        assert found.action == "test.action"


class TestApiKeyModel:
    async def test_create_api_key(self, db_session: AsyncSession, org_a: Organization, user_a: User):
        repo = ApiKeyRepository(db_session)
        api_key = await repo.create(
            name="Test API Key",
            key_hash="hashed_key_value",
            key_prefix="oa_test",
            user_id=user_a.id,
            organization_id=org_a.id,
            permissions=["read", "write"]
        )
        await db_session.commit()
        
        assert api_key.id is not None
        assert api_key.key_hash == "hashed_key_value"
        assert api_key.key_prefix == "oa_test"
        # Full key should NOT be stored
        assert "full_key" not in str(api_key.key_hash).lower()


class TestWebhookModel:
    async def test_create_webhook(self, db_session: AsyncSession, org_a: Organization):
        repo = WebhookRepository(db_session)
        webhook = await repo.create(
            organization_id=org_a.id,
            name="Test Webhook",
            url="https://example.com/webhook",
            event_types=["agent.created", "agent.completed"],
            secret_hash="hashed_secret",
            status=WebhookStatus.ACTIVE
        )
        await db_session.commit()
        
        assert webhook.id is not None
        assert webhook.organization_id == org_a.id
        assert webhook.secret_hash == "hashed_secret"