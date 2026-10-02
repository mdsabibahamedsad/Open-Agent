import pytest
import pytest_asyncio
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.models import (
    User, UserStatus,
    Organization, OrganizationStatus,
    Membership, MembershipRole, MembershipStatus,
    Agent, AgentVersion, AgentType, AgentStatus,
    Workflow, WorkflowVersion, WorkflowStatus,
    WorkflowExecution, WorkflowExecutionStatus, WorkflowExecutionTriggerType,
    Task, TaskStatus,
    AgentRun, AgentRunStatus,
    ExecutionEvent,
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


@pytest_asyncio.fixture
async def org_a(db_session: AsyncSession) -> Organization:
    repo = OrganizationRepository(db_session)
    org = await repo.create(
        name="Organization A",
        slug="org-a-isolation",
        status=OrganizationStatus.ACTIVE
    )
    await db_session.commit()
    return org


@pytest_asyncio.fixture
async def org_b(db_session: AsyncSession) -> Organization:
    repo = OrganizationRepository(db_session)
    org = await repo.create(
        name="Organization B",
        slug="org-b-isolation",
        status=OrganizationStatus.ACTIVE
    )
    await db_session.commit()
    return org


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    repo = UserRepository(db_session)
    user = await repo.create(
        email="user-a-isolation@example.com",
        display_name="User A",
        status=UserStatus.ACTIVE
    )
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    repo = UserRepository(db_session)
    user = await repo.create(
        email="user-b-isolation@example.com",
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


async def create_agent(db_session: AsyncSession, org: Organization, name: str) -> Agent:
    repo = AgentRepository(db_session)
    agent = await repo.create(
        organization_id=org.id,
        name=name,
        slug=name.lower().replace(" ", "-"),
        status=AgentStatus.ACTIVE,
        agent_type=AgentType.CHAT
    )
    await db_session.commit()
    return agent


async def create_workflow(db_session: AsyncSession, org: Organization, name: str) -> Workflow:
    repo = WorkflowRepository(db_session)
    workflow = await repo.create(
        organization_id=org.id,
        name=name,
        slug=name.lower().replace(" ", "-"),
        status=WorkflowStatus.ACTIVE
    )
    await db_session.commit()
    return workflow


async def create_credential(db_session: AsyncSession, org: Organization, name: str) -> Credential:
    repo = CredentialRepository(db_session)
    credential = await repo.create(
        organization_id=org.id,
        name=name,
        provider="test",
        credential_type=CredentialType.API_KEY,
        encrypted_data="encrypted",
        status=CredentialStatus.ACTIVE
    )
    await db_session.commit()
    return credential


class TestAgentTenantIsolation:
    async def test_org_a_cannot_access_org_b_agents(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        # Create agent in org A
        agent_a = await create_agent(db_session, org_a, "Agent A")
        
        # Create agent in org B
        agent_b = await create_agent(db_session, org_b, "Agent B")
        
        # Query org A agents
        repo = AgentRepository(db_session)
        org_a_agents = await repo.list(organization_id=org_a.id)
        org_a_agent_ids = {a.id for a in org_a_agents}
        
        # Query org B agents
        org_b_agents = await repo.list(organization_id=org_b.id)
        org_b_agent_ids = {a.id for a in org_b_agents}
        
        # Verify isolation
        assert agent_a.id in org_a_agent_ids
        assert agent_a.id not in org_b_agent_ids
        assert agent_b.id in org_b_agent_ids
        assert agent_b.id not in org_a_agent_ids
        
        # Verify get_by_id_with_org fails cross-org
        assert await repo.get_by_id_with_org(agent_a.id, org_a.id) is not None
        assert await repo.get_by_id_with_org(agent_a.id, org_b.id) is None
        assert await repo.get_by_id_with_org(agent_b.id, org_b.id) is not None
        assert await repo.get_by_id_with_org(agent_b.id, org_a.id) is None


class TestWorkflowTenantIsolation:
    async def test_org_a_cannot_access_org_b_workflows(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        workflow_a = await create_workflow(db_session, org_a, "Workflow A")
        workflow_b = await create_workflow(db_session, org_b, "Workflow B")
        
        repo = WorkflowRepository(db_session)
        org_a_workflows = await repo.list(organization_id=org_a.id)
        org_b_workflows = await repo.list(organization_id=org_b.id)
        
        org_a_ids = {w.id for w in org_a_workflows}
        org_b_ids = {w.id for w in org_b_workflows}
        
        assert workflow_a.id in org_a_ids
        assert workflow_a.id not in org_b_ids
        assert workflow_b.id in org_b_ids
        assert workflow_b.id not in org_a_ids
        
        # Verify get_by_id_with_org fails cross-org
        assert await repo.get_by_id_with_org(workflow_a.id, org_a.id) is not None
        assert await repo.get_by_id_with_org(workflow_a.id, org_b.id) is None


class TestWorkflowExecutionTenantIsolation:
    async def test_org_a_cannot_access_org_b_executions(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        workflow_a = await create_workflow(db_session, org_a, "Workflow A")
        workflow_b = await create_workflow(db_session, org_b, "Workflow B")
        
        exec_repo = WorkflowExecutionRepository(db_session)
        exec_a = await exec_repo.create(
            organization_id=org_a.id,
            workflow_id=workflow_a.id,
            status=WorkflowExecutionStatus.RUNNING,
            trigger_type=WorkflowExecutionTriggerType.MANUAL
        )
        exec_b = await exec_repo.create(
            organization_id=org_b.id,
            workflow_id=workflow_b.id,
            status=WorkflowExecutionStatus.RUNNING,
            trigger_type=WorkflowExecutionTriggerType.MANUAL
        )
        await db_session.commit()
        
        org_a_execs = await exec_repo.list(organization_id=org_a.id)
        org_b_execs = await exec_repo.list(organization_id=org_b.id)
        
        org_a_ids = {e.id for e in org_a_execs}
        org_b_ids = {e.id for e in org_b_execs}
        
        assert exec_a.id in org_a_ids
        assert exec_a.id not in org_b_ids
        assert exec_b.id in org_b_ids
        assert exec_b.id not in org_a_ids


class TestAgentRunTenantIsolation:
    async def test_org_a_cannot_access_org_b_agent_runs(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        agent_a = await create_agent(db_session, org_a, "Agent A")
        agent_b = await create_agent(db_session, org_b, "Agent B")
        
        run_repo = AgentRunRepository(db_session)
        run_a = await run_repo.create(
            organization_id=org_a.id,
            agent_id=agent_a.id,
            status=AgentRunStatus.RUNNING,
            input={}
        )
        run_b = await run_repo.create(
            organization_id=org_b.id,
            agent_id=agent_b.id,
            status=AgentRunStatus.RUNNING,
            input={}
        )
        await db_session.commit()
        
        org_a_runs = await run_repo.list(organization_id=org_a.id)
        org_b_runs = await run_repo.list(organization_id=org_b.id)
        
        org_a_ids = {r.id for r in org_a_runs}
        org_b_ids = {r.id for r in org_b_runs}
        
        assert run_a.id in org_a_ids
        assert run_a.id not in org_b_ids
        assert run_b.id in org_b_ids
        assert run_b.id not in org_a_ids


class TestExecutionEventTenantIsolation:
    async def test_org_a_cannot_access_org_b_events(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        event_repo = ExecutionEventRepository(db_session)
        
        event_a = await event_repo.create_event(
            organization_id=org_a.id,
            event_type="test.event",
            payload={"data": "A"}
        )
        event_b = await event_repo.create_event(
            organization_id=org_b.id,
            event_type="test.event",
            payload={"data": "B"}
        )
        await db_session.commit()
        
        org_a_events = await event_repo.list(organization_id=org_a.id)
        org_b_events = await event_repo.list(organization_id=org_b.id)
        
        org_a_ids = {e.id for e in org_a_events}
        org_b_ids = {e.id for e in org_b_events}
        
        assert event_a.id in org_a_ids
        assert event_a.id not in org_b_ids
        assert event_b.id in org_b_ids
        assert event_b.id not in org_a_ids


class TestCredentialTenantIsolation:
    async def test_org_a_cannot_access_org_b_credentials(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        cred_a = await create_credential(db_session, org_a, "Credential A")
        cred_b = await create_credential(db_session, org_b, "Credential B")
        
        repo = CredentialRepository(db_session)
        org_a_creds = await repo.list(organization_id=org_a.id)
        org_b_creds = await repo.list(organization_id=org_b.id)
        
        org_a_ids = {c.id for c in org_a_creds}
        org_b_ids = {c.id for c in org_b_creds}
        
        assert cred_a.id in org_a_ids
        assert cred_a.id not in org_b_ids
        assert cred_b.id in org_b_ids
        assert cred_b.id not in org_a_ids
        
        # Verify get_by_id_with_org fails cross-org
        assert await repo.get_by_id_with_org(cred_a.id, org_a.id) is not None
        assert await repo.get_by_id_with_org(cred_a.id, org_b.id) is None


class TestAuditLogTenantIsolation:
    async def test_org_a_cannot_access_org_b_audit_logs(self, db_session: AsyncSession, org_a: Organization, org_b: Organization, user_a: User, user_b: User):
        repo = AuditLogRepository(db_session)
        
        log_a = await repo.log(
            organization_id=org_a.id,
            actor_user_id=user_a.id,
            action="test.action",
            resource_type="test",
            resource_id=uuid4()
        )
        log_b = await repo.log(
            organization_id=org_b.id,
            actor_user_id=user_b.id,
            action="test.action",
            resource_type="test",
            resource_id=uuid4()
        )
        await db_session.commit()
        
        org_a_logs = await repo.list(organization_id=org_a.id)
        org_b_logs = await repo.list(organization_id=org_b.id)
        
        org_a_ids = {l.id for l in org_a_logs}
        org_b_ids = {l.id for l in org_b_logs}
        
        assert log_a.id in org_a_ids
        assert log_a.id not in org_b_ids
        assert log_b.id in org_b_ids
        assert log_b.id not in org_a_ids


class TestTaskTenantIsolation:
    async def test_org_a_cannot_access_org_b_tasks(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        repo = TaskRepository(db_session)
        
        task_a = await repo.create(
            organization_id=org_a.id,
            type="test_task",
            status=TaskStatus.PENDING,
            payload={}
        )
        task_b = await repo.create(
            organization_id=org_b.id,
            type="test_task",
            status=TaskStatus.PENDING,
            payload={}
        )
        await db_session.commit()
        
        org_a_tasks = await repo.list(organization_id=org_a.id)
        org_b_tasks = await repo.list(organization_id=org_b.id)
        
        org_a_ids = {t.id for t in org_a_tasks}
        org_b_ids = {t.id for t in org_b_tasks}
        
        assert task_a.id in org_a_ids
        assert task_a.id not in org_b_ids
        assert task_b.id in org_b_ids
        assert task_b.id not in org_a_ids


class TestIntegrationTenantIsolation:
    async def test_org_a_cannot_access_org_b_integrations(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        cred_a = await create_credential(db_session, org_a, "Cred A")
        cred_b = await create_credential(db_session, org_b, "Cred B")
        
        repo = IntegrationRepository(db_session)
        int_a = await repo.create(
            organization_id=org_a.id,
            provider=IntegrationProvider.GITHUB,
            name="GitHub A",
            status=IntegrationStatus.ACTIVE,
            credential_id=cred_a.id
        )
        int_b = await repo.create(
            organization_id=org_b.id,
            provider=IntegrationProvider.GITHUB,
            name="GitHub B",
            status=IntegrationStatus.ACTIVE,
            credential_id=cred_b.id
        )
        await db_session.commit()
        
        org_a_ints = await repo.list(organization_id=org_a.id)
        org_b_ints = await repo.list(organization_id=org_b.id)
        
        org_a_ids = {i.id for i in org_a_ints}
        org_b_ids = {i.id for i in org_b_ints}
        
        assert int_a.id in org_a_ids
        assert int_a.id not in org_b_ids
        assert int_b.id in org_b_ids
        assert int_b.id not in org_a_ids


class TestMCPServerTenantIsolation:
    async def test_org_a_cannot_access_org_b_mcp_servers(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        repo = MCPServerRepository(db_session)
        
        mcp_a = await repo.create(
            organization_id=org_a.id,
            name="MCP Server A",
            server_url="http://mcp-a.example.com",
            transport=MCPTransport.STDIO,
            status=MCPServerStatus.ACTIVE
        )
        mcp_b = await repo.create(
            organization_id=org_b.id,
            name="MCP Server B",
            server_url="http://mcp-b.example.com",
            transport=MCPTransport.STDIO,
            status=MCPServerStatus.ACTIVE
        )
        await db_session.commit()
        
        org_a_mcps = await repo.list(organization_id=org_a.id)
        org_b_mcps = await repo.list(organization_id=org_b.id)
        
        org_a_ids = {m.id for m in org_a_mcps}
        org_b_ids = {m.id for m in org_b_mcps}
        
        assert mcp_a.id in org_a_ids
        assert mcp_a.id not in org_b_ids
        assert mcp_b.id in org_b_ids
        assert mcp_b.id not in org_a_ids


class TestMemoryTenantIsolation:
    async def test_org_a_cannot_access_org_b_memories(self, db_session: AsyncSession, org_a: Organization, org_b: Organization, user_a: User, user_b: User):
        repo = MemoryRepository(db_session)
        
        mem_a = await repo.create(
            organization_id=org_a.id,
            user_id=user_a.id,
            memory_type=MemoryType.LONG_TERM,
            content="Memory A"
        )
        mem_b = await repo.create(
            organization_id=org_b.id,
            user_id=user_b.id,
            memory_type=MemoryType.LONG_TERM,
            content="Memory B"
        )
        await db_session.commit()
        
        org_a_mems = await repo.list(organization_id=org_a.id)
        org_b_mems = await repo.list(organization_id=org_b.id)
        
        org_a_ids = {m.id for m in org_a_mems}
        org_b_ids = {m.id for m in org_b_mems}
        
        assert mem_a.id in org_a_ids
        assert mem_a.id not in org_b_ids
        assert mem_b.id in org_b_ids
        assert mem_b.id not in org_a_ids


class TestConversationTenantIsolation:
    async def test_org_a_cannot_access_org_b_conversations(self, db_session: AsyncSession, org_a: Organization, org_b: Organization, user_a: User, user_b: User):
        repo = ConversationRepository(db_session)
        
        conv_a = await repo.create(
            organization_id=org_a.id,
            user_id=user_a.id,
            status=ConversationStatus.ACTIVE
        )
        conv_b = await repo.create(
            organization_id=org_b.id,
            user_id=user_b.id,
            status=ConversationStatus.ACTIVE
        )
        await db_session.commit()
        
        org_a_convs = await repo.list(organization_id=org_a.id)
        org_b_convs = await repo.list(organization_id=org_b.id)
        
        org_a_ids = {c.id for c in org_a_convs}
        org_b_ids = {c.id for c in org_b_convs}
        
        assert conv_a.id in org_a_ids
        assert conv_a.id not in org_b_ids
        assert conv_b.id in org_b_ids
        assert conv_b.id not in org_a_ids


class TestApprovalTenantIsolation:
    async def test_org_a_cannot_access_org_b_approvals(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        repo = ApprovalRepository(db_session)
        
        approval_a = await repo.create(
            organization_id=org_a.id,
            approval_type=ApprovalType.TOOL_USE,
            status=ApprovalStatus.PENDING,
            payload={}
        )
        approval_b = await repo.create(
            organization_id=org_b.id,
            approval_type=ApprovalType.TOOL_USE,
            status=ApprovalStatus.PENDING,
            payload={}
        )
        await db_session.commit()
        
        org_a_approvals = await repo.list(organization_id=org_a.id)
        org_b_approvals = await repo.list(organization_id=org_b.id)
        
        org_a_ids = {a.id for a in org_a_approvals}
        org_b_ids = {a.id for a in org_b_approvals}
        
        assert approval_a.id in org_a_ids
        assert approval_a.id not in org_b_ids
        assert approval_b.id in org_b_ids
        assert approval_b.id not in org_a_ids


class TestEvaluationTenantIsolation:
    async def test_org_a_cannot_access_org_b_evaluations(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        repo = EvaluationRepository(db_session)
        
        eval_a = await repo.create(
            organization_id=org_a.id,
            evaluator_type=EvaluatorType.AUTOMATED,
            status=EvaluationStatus.PENDING,
            criteria={}
        )
        eval_b = await repo.create(
            organization_id=org_b.id,
            evaluator_type=EvaluatorType.AUTOMATED,
            status=EvaluationStatus.PENDING,
            criteria={}
        )
        await db_session.commit()
        
        org_a_evals = await repo.list(organization_id=org_a.id)
        org_b_evals = await repo.list(organization_id=org_b.id)
        
        org_a_ids = {e.id for e in org_a_evals}
        org_b_ids = {e.id for e in org_b_evals}
        
        assert eval_a.id in org_a_ids
        assert eval_a.id not in org_b_ids
        assert eval_b.id in org_b_ids
        assert eval_b.id not in org_a_ids


class TestWebhookTenantIsolation:
    async def test_org_a_cannot_access_org_b_webhooks(self, db_session: AsyncSession, org_a: Organization, org_b: Organization):
        repo = WebhookRepository(db_session)
        
        webhook_a = await repo.create(
            organization_id=org_a.id,
            name="Webhook A",
            url="https://a.example.com/webhook",
            event_types=["test.event"],
            secret_hash="hash_a",
            status=WebhookStatus.ACTIVE
        )
        webhook_b = await repo.create(
            organization_id=org_b.id,
            name="Webhook B",
            url="https://b.example.com/webhook",
            event_types=["test.event"],
            secret_hash="hash_b",
            status=WebhookStatus.ACTIVE
        )
        await db_session.commit()
        
        org_a_webhooks = await repo.list(organization_id=org_a.id)
        org_b_webhooks = await repo.list(organization_id=org_b.id)
        
        org_a_ids = {w.id for w in org_a_webhooks}
        org_b_ids = {w.id for w in org_b_webhooks}
        
        assert webhook_a.id in org_a_ids
        assert webhook_a.id not in org_b_ids
        assert webhook_b.id in org_b_ids
        assert webhook_b.id not in org_a_ids


class TestApiKeyTenantIsolation:
    async def test_org_a_cannot_access_org_b_api_keys(self, db_session: AsyncSession, org_a: Organization, org_b: Organization, user_a: User, user_b: User):
        repo = ApiKeyRepository(db_session)
        
        key_a = await repo.create(
            name="Key A",
            key_hash="hash_a",
            key_prefix="oa_a",
            user_id=user_a.id,
            organization_id=org_a.id,
            permissions=["read"]
        )
        key_b = await repo.create(
            name="Key B",
            key_hash="hash_b",
            key_prefix="oa_b",
            user_id=user_b.id,
            organization_id=org_b.id,
            permissions=["read"]
        )
        await db_session.commit()
        
        org_a_keys = await repo.list(organization_id=org_a.id)
        org_b_keys = await repo.list(organization_id=org_b.id)
        
        org_a_ids = {k.id for k in org_a_keys}
        org_b_ids = {k.id for k in org_b_keys}
        
        assert key_a.id in org_a_ids
        assert key_a.id not in org_b_ids
        assert key_b.id in org_b_ids
        assert key_b.id not in org_a_ids