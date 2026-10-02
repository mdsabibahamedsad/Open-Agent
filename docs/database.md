# OpenAgent Database Architecture

## Overview

This document describes the database architecture for OpenAgent, an AI Workforce Operating System. The database is built on PostgreSQL with SQLAlchemy 2.0+ (async) and uses Alembic for migrations.

## Design Principles

1. **PostgreSQL-first**: All features leverage PostgreSQL capabilities (UUID, JSONB, ENUMs, arrays, etc.)
2. **UUID Primary Keys**: All public identifiers use UUIDv4 for security and distribution
3. **UTC Timestamps**: All timestamps are timezone-aware UTC
4. **Explicit Foreign Keys**: All relationships enforced at database level
5. **Appropriate Indexes**: Composite indexes for common query patterns
6. **Explicit Constraints**: Uniqueness and check constraints at database level
7. **Tenant Isolation**: Every organization-owned entity scoped to `organization_id`
8. **Migration-driven**: All schema changes via Alembic migrations
9. **No Plaintext Secrets**: Credentials and API keys stored as hashes/encrypted data only

## Entity Relationship Diagram

```
┌─────────────┐       ┌──────────────────┐       ┌─────────────┐
│   users     │◄──────│   memberships    │──────►│organizations│
└─────────────┘       └──────────────────┘       └──────┬──────┘
                                                         │
         ┌──────────────┬──────────────┬────────────────┼────────────────┐
         ▼              ▼              ▼                ▼                ▼
    ┌─────────┐   ┌───────────┐  ┌──────────┐   ┌───────────┐   ┌──────────┐
    │  agents │   │ workflows │  │credentials│   │integrations│  │mcp_servers│
    └────┬────┘   └─────┬─────┘  └────┬─────┘   └─────┬─────┘   └────┬─────┘
         │              │             │               │              │
         ▼              ▼             ▼               ▼              ▼
    ┌─────────┐   ┌───────────┐  ┌──────────┐   ┌───────────┐   ┌──────────┐
    │agent_ver│   │workflow_  │  │          │   │           │   │          │
    │  sions  │   │ versions  │  │          │   │           │   │          │
    └────┬────┘   └─────┬─────┘  └──────────┘   └───────────┘   └──────────┘
         │              │
         ▼              ▼
    ┌─────────┐   ┌───────────┐
    │agent_   │   │workflow_  │
    │  runs   │   │executions │
    └────┬────┘   └─────┬─────┘
         │              │
         └──────┬───────┘
                ▼
         ┌─────────────┐
         │execution_   │
         │   events    │
         └─────────────┘
```

## Core Domains

### 1. Identity & Access

#### users
- `id` (UUID, PK)
- `email` (String, unique, indexed)
- `display_name` (String, nullable)
- `avatar_url` (String, nullable)
- `status` (ENUM: active, inactive, suspended, pending_verification)
- `is_superadmin` (Boolean)
- `created_at`, `updated_at`, `deleted_at` (timestamps)

#### organizations
- `id` (UUID, PK)
- `name` (String)
- `slug` (String, unique, indexed)
- `description` (Text, nullable)
- `avatar_url` (String, nullable)
- `status` (ENUM: active, inactive, suspended, deleted)
- `settings` (JSONB)
- `created_at`, `updated_at`, `deleted_at`

#### memberships
- `id` (UUID, PK)
- `user_id` (FK → users.id, CASCADE)
- `organization_id` (FK → organizations.id, CASCADE)
- `role` (ENUM: owner, admin, member, viewer)
- `status` (ENUM: active, pending, suspended, revoked)
- `created_at`, `updated_at`
- **Unique**: (user_id, organization_id)

#### sessions
- `id` (UUID, PK)
- `user_id` (FK → users.id, CASCADE)
- `token_hash` (String, unique, indexed)
- `expires_at` (DateTime, indexed)
- `user_agent`, `ip_address`
- `created_at`

#### api_keys
- `id` (UUID, PK)
- `name` (String)
- `key_hash` (String, unique, indexed) — **never stores plaintext key**
- `key_prefix` (String, indexed) — for identification (e.g., "oa_abc123")
- `user_id` (FK → users.id, SET NULL, nullable)
- `organization_id` (FK → organizations.id, SET NULL, nullable)
- `permissions` (JSONB)
- `expires_at`, `last_used_at`
- `created_at`, `updated_at`, `deleted_at`

### 2. Agents

#### agents
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `name` (String)
- `slug` (String, indexed)
- `description` (Text, nullable)
- `status` (ENUM: draft, active, archived, deprecated)
- `agent_type` (ENUM: chat, workflow, autonomous, assistant)
- `metadata` (JSONB)
- `created_at`, `updated_at`, `deleted_at`
- **Unique**: (organization_id, slug)

#### agent_versions
- `id` (UUID, PK)
- `agent_id` (FK → agents.id, CASCADE, indexed)
- `version` (String)
- `name` (String)
- `instructions` (Text, nullable)
- `configuration` (JSONB)
- `status` (String)
- `created_by` (FK → users.id, SET NULL)
- `created_at`
- **Unique**: (agent_id, version)

### 3. Workflows

#### workflows
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `name` (String)
- `slug` (String, indexed)
- `description` (Text, nullable)
- `status` (ENUM: draft, active, archived, deprecated)
- `metadata` (JSONB)
- `created_at`, `updated_at`, `deleted_at`
- **Unique**: (organization_id, slug)

#### workflow_versions
- `id` (UUID, PK)
- `workflow_id` (FK → workflows.id, CASCADE, indexed)
- `version` (String)
- `definition` (JSONB) — serialized workflow graph
- `status` (String)
- `created_by` (FK → users.id, SET NULL)
- `created_at`
- **Unique**: (workflow_id, version)

#### workflow_executions
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `workflow_id` (FK → workflows.id, CASCADE, indexed)
- `workflow_version_id` (FK → workflow_versions.id, SET NULL, indexed)
- `status` (ENUM: queued, running, paused, waiting, completed, failed, cancelled)
- `trigger_type` (ENUM: manual, scheduled, webhook, api, event)
- `started_at`, `completed_at`
- `error_code`, `error_message`
- `metadata` (JSONB)
- `created_at`

### 4. Execution

#### tasks
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `type` (String, indexed)
- `status` (ENUM: pending, queued, running, completed, failed, cancelled, retrying)
- `priority` (Integer, default 5)
- `payload` (JSONB)
- `result` (JSONB, nullable)
- `error` (Text, nullable)
- `attempts`, `max_attempts` (Integer)
- `available_at` (DateTime, indexed)
- `started_at`, `completed_at`
- `created_at`, `updated_at`

#### agent_runs
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `agent_id` (FK → agents.id, CASCADE, indexed)
- `agent_version_id` (FK → agent_versions.id, SET NULL, indexed)
- `workflow_execution_id` (FK → workflow_executions.id, SET NULL, indexed)
- `status` (ENUM: queued, running, paused, waiting, completed, failed, cancelled)
- `input` (JSONB)
- `output` (JSONB, nullable)
- `error` (Text, nullable)
- `started_at`, `completed_at`
- `metadata` (JSONB)
- `created_at`, `updated_at`

#### execution_events
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `run_id` (FK → agent_runs.id, CASCADE, nullable, indexed)
- `workflow_execution_id` (FK → workflow_executions.id, CASCADE, nullable, indexed)
- `event_type` (String, indexed)
- `sequence` (Integer)
- `timestamp` (DateTime, indexed)
- `payload` (JSONB)
- `created_at`
- **Composite indexes**: (run_id, sequence), (workflow_execution_id, sequence)

### 5. Tools & Integrations

#### tools
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, nullable, indexed)
- `name` (String)
- `slug` (String, indexed)
- `description` (Text, nullable)
- `tool_type` (ENUM: builtin, custom, mcp, api, community)
- `status` (ENUM: active, inactive, deprecated, development)
- `configuration` (JSONB)
- `metadata` (JSONB)
- `created_at`, `updated_at`, `deleted_at`
- **Unique**: (organization_id, slug)

#### credentials
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `name` (String)
- `provider` (String, indexed)
- `credential_type` (ENUM: api_key, oauth_token, basic_auth, bearer_token, certificate, ssh_key, database_url, custom)
- `encrypted_data` (Text) — **encrypted secret material only**
- `metadata` (JSONB)
- `status` (ENUM: active, inactive, expired, revoked)
- `expires_at`
- `created_at`, `updated_at`, `deleted_at`

#### integrations
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `provider` (ENUM: github, gitlab, google, slack, discord, notion, telegram, whatsapp, hubspot, stripe, postgres, mysql, mongodb, redis, aws, gcp, azure, custom)
- `name` (String)
- `status` (ENUM: active, inactive, error, pending, revoked)
- `configuration` (JSONB)
- `credential_id` (FK → credentials.id, SET NULL, indexed)
- `metadata` (JSONB)
- `created_at`, `updated_at`, `deleted_at`

#### mcp_servers
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `name` (String)
- `server_url` (String)
- `transport` (ENUM: stdio, sse, http, websocket)
- `status` (ENUM: active, inactive, connecting, error, disconnected)
- `configuration` (JSONB)
- `credential_id` (FK → credentials.id, SET NULL, indexed)
- `metadata` (JSONB)
- `created_at`, `updated_at`, `deleted_at`

### 6. Memory & Conversations

#### memories
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `user_id` (FK → users.id, SET NULL, indexed)
- `agent_id` (FK → agents.id, SET NULL, indexed)
- `memory_type` (ENUM: short_term, long_term, semantic, episodic, procedural, working)
- `content` (Text)
- `metadata` (JSONB)
- `embedding` (ARRAY[Float], nullable) — for pgvector
- `expires_at` (indexed)
- `created_at`, `updated_at`

#### conversations
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `user_id` (FK → users.id, CASCADE, indexed)
- `agent_id` (FK → agents.id, SET NULL, indexed)
- `title` (String, nullable)
- `status` (ENUM: active, archived, deleted)
- `metadata` (JSONB)
- `created_at`, `updated_at`, `deleted_at`

#### messages
- `id` (UUID, PK)
- `conversation_id` (FK → conversations.id, CASCADE, indexed)
- `role` (ENUM: system, user, assistant, tool, developer)
- `content` (Text)
- `metadata` (JSONB)
- `created_at`

### 7. Human-in-the-Loop & Evaluation

#### approvals
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `run_id` (FK → agent_runs.id, SET NULL, indexed)
- `workflow_execution_id` (FK → workflow_executions.id, SET NULL, indexed)
- `approval_type` (ENUM: tool_use, resource_access, data_sharing, workflow_execution, agent_action, custom)
- `status` (ENUM: pending, approved, rejected, expired, cancelled)
- `requested_by` (FK → users.id, SET NULL)
- `approved_by` (FK → users.id, SET NULL)
- `payload` (JSONB)
- `decision` (JSONB, nullable)
- `expires_at`, `resolved_at`
- `created_at`

#### evaluations
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `run_id` (FK → agent_runs.id, SET NULL, indexed)
- `workflow_execution_id` (FK → workflow_executions.id, SET NULL, indexed)
- `evaluator_type` (ENUM: human, llm, rule_based, automated, composite)
- `status` (ENUM: pending, running, completed, failed, passed, uncertain, skipped, cancelled, error)
- `score` (Float, nullable)
- `criteria` (JSONB, includes goal block + criteria hash)
- `result` (JSONB, nullable: reason codes, consensus, correction strategy)
- `completed_at`
- `created_at`
- MP20+: `evaluation_type`, `task_id`, `agent_id`, `workflow_id`,
  `parent_evaluation_id` (correction lineage, SET NULL), `attempt_number`,
  `decision`, `confidence`, `failure_class/reason`, `uncertainty_reason`,
  `input_hash`, `output_hash`, `evaluator_version`, `rubric_version`,
  `policy_version`, `model_version`, `verification_version`
- **Terminal states immutable**: correction creates NEW linked rows.

#### evaluation_evidence
- `id` (UUID, PK), `evaluation_id` (FK → evaluations.id, CASCADE, indexed)
- `organization_id` (FK, CASCADE, indexed), `evidence_type`, `trust` (indexed)
- `content` (JSONB, redacted), `source*`, `content_hash`, `captured_at`
- **Append-only while PENDING/RUNNING**; hash re-verified on read.

#### evaluation_results
- Immutable per-evaluator votes: `source`, `decision`, `score`, `confidence`,
  `reason_codes`, `weight`, `model`. Disagreement never hidden.

#### verification_checks
- `evaluation_id` (indexed), `name`, `kind`, `passed`, `reason`,
  `required`, `critical_safety`.

#### evaluation_disagreements
- `evaluation_id` (indexed), `votes`, `policy`, `resolution`.

#### evaluation_rubrics / evaluation_rubric_versions
- Org rubrics: `name`, `criteria`, thresholds, `is_active`, `version`;
  criteria edits bump version + snapshot row.

#### correction_plans / correction_attempts
- Plans: `evaluation_id` (indexed), `attempt_number`, `failure_class`,
  `root_cause` (symptom/cause/evidence/correction/expected), strategy,
  `changes`, `risk_level`, `approval_required`, `approval_id`, `status`.
- Attempts: `plan_id` (indexed), action/outcome (redacted), `status`,
  `failure_signature` (loop detection).

#### evaluation_feedback
- Append-only human verdicts (`correct|incorrect|partially_correct`); history untouched.

#### quality_gates
- `name`, `required_checks`, `thresholds`, `failure_behavior`,
  `approval_required`, `is_active`, `version`.

#### benchmarks / benchmark_runs
- Benchmarks: `name`, `dataset` (data, never code), `criteria`.
- Runs: `benchmark_id` (indexed), `status`, `scores`, `items`,
  `baseline_run_id`, `regression`.

### 8. Audit & Observability
#### audit_logs
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `actor_user_id` (FK → users.id, SET NULL, indexed)
- `action` (String, indexed)
- `resource_type` (String, indexed)
- `resource_id` (UUID, nullable, indexed)
- `ip_address` (String, nullable)
- `user_agent` (Text, nullable)
- `metadata` (JSONB)
- `created_at`
- **Append-only**: Application should not update/delete audit logs

#### webhooks
- `id` (UUID, PK)
- `organization_id` (FK → organizations.id, CASCADE, indexed)
- `name` (String)
- `url` (String)
- `event_types` (JSONB array)
- `secret_hash` (String) — **never stores plaintext secret**
- `status` (ENUM: active, inactive, failed, pending)
- `metadata` (JSONB)
- `created_at`, `updated_at`, `deleted_at`

### 9. Multi-Agent Orchestration (MP13, migration `012_add_orchestration`)

All tables carry `organization_id` (CASCADE, indexed) with composite
`(organization_id, status)` / `(organization_id, created_at)` indexes.

- `orchestration_runs` — objective, status enum (created → ... →
  succeeded/partially_succeeded/failed/cancelled/timed_out), root_agent,
  team, budget/usage JSONB, final_result, idempotency_key.
- `orchestration_tasks` — run FK, parent FK, assigned_agent FK, agent_run FK,
  `external_task_id` (unique per run), title/instructions, status enum,
  priority, dependency_policy, required_capabilities/permissions, risk_level,
  requires_approval, input/output, retry counters + strategy, timeout, depth,
  aggregation_strategy, leases (`lease_owner`, `lease_expires_at`,
  `last_heartbeat_at`).
- `orchestration_task_dependencies` — `(task_id, depends_on_task_id)` unique.
- `agent_relationships` — source/target agent FKs + relationship enum, unique
  per (org, source, target, type).
- `agent_capabilities` — agent FK + name unique, version, required
  tools/permissions, risk_level, availability.
- `agent_messages` — run/sender/recipient/task FKs, message_type, payload,
  correlation_id.
- `agent_handoffs` — run/task/from/to agent FKs, structured package JSONB.
- `orchestration_task_attempts` — attempt history, unique (task, number).
- `orchestration_budget_ledgers` — one per run, limits + consumed counters.
- `orchestration_events` — run/task/agent FKs, event_type, payload,
  trace/span ids.
- `agent_conflicts` — sources/claims/evidence/confidence + resolution.

Reuses `agents`, `agent_versions`, `agent_runs`, `execution_events`, `tools`,
`mcp_servers` — no duplicates.

### 9. Management Layer (MP14, migration `013_add_management`)

All tables carry `organization_id` (CASCADE, indexed) with composite
`(organization_id, status)` indexes.

- `manager_profiles` — agent FK (unique), label, status, capabilities,
  delegation/review/escalation/team policies, budget share, limits, allowed
  actions, scope, department/team FKs.
- `agent_contracts` — run/task/agent/manager FKs, objective, responsibilities,
  inputs/outputs, capabilities, constraints, permissions (required, not
  granted), budget, deadline, quality requirements, acceptance criteria,
  escalation conditions, max revisions, idempotency key.
- `delegation_requests` — run/task/contract/source/target FKs, reason,
  capabilities, budget, deadline, policy, status enum, decision metadata,
  expiry, idempotency key.
- `agent_commitments` — delegation/task/agent FKs, deadline, budget, expected
  output, status lifecycle.
- `handoff_packages` — run/task/contract/source/target FKs, mode, package
  JSONB, context manifest JSONB, status enum lifecycle, acceptance/completion
  timestamps, idempotency key. Append-only (complements `agent_handoffs`).
- `review_results` — run/task/reviewer FKs, status enum, criteria results,
  issues, required changes, evidence, revision number, gate result.
- `escalations` — run/task/source/holder FKs, trigger, reason, severity,
  status enum, chain + level, recommended action, history, human approval FK.
- `agent_departments` — org + slug unique, name, description.
- `dynamic_teams` — run/task/manager/department FKs, name, type, status enum,
  budget, idempotency key.
- `team_charters` — team FK unique, objective, scope, responsibilities,
  communication rules, completion criteria, deadline, budget.
- `dynamic_team_memberships` — team/agent FKs unique, role,
  responsibilities, permissions (required), task scope, status.
- `agent_availability` / `agent_capacity` — agent FK unique, state/load and
  configurable limits + usage.
- `plan_versions` — run FK, version unique per run, reason, creator,
  changes, parent version, plan snapshot (history never overwritten).
- `collaboration_requests` — run/task/from/to FKs, action, payload, status.
- `manager_decisions` — run/manager/task FKs, decision type, selected
  action, alternatives, policy basis, concise rationale.

## Indexing Strategy

### Primary Indexes
- All PKs automatically indexed
- All FKs indexed explicitly

### Composite Indexes (Critical for Tenant Isolation)
| Table | Index Columns |
|-------|---------------|
| agents | (organization_id, created_at) |
| agents | (organization_id, status) |
| workflows | (organization_id, created_at) |
| workflows | (organization_id, status) |
| workflow_executions | (organization_id, status) |
| workflow_executions | (organization_id, created_at) |
| agent_runs | (organization_id, status) |
| agent_runs | (organization_id, created_at) |
| execution_events | (organization_id, created_at) |
| execution_events | (run_id, sequence) |
| execution_events | (workflow_execution_id, sequence) |
| audit_logs | (organization_id, action) |
| audit_logs | (organization_id, created_at) |
| audit_logs | (resource_type, resource_id) |

### Partial Indexes
- `deleted_at` indexes for soft-delete filtering

## Tenant Isolation Enforcement

### Database Level
- Every organization-owned table has `organization_id` FK with CASCADE
- Composite unique constraints include `organization_id`
- All queries **must** filter by `organization_id`

### Repository Pattern
```python
# CORRECT - organization-scoped
agent = await repo.get_by_id_with_org(agent_id, organization_id)
agents = await repo.list(organization_id=org_id)

# INCORRECT - no organization scoping
agent = await repo.get_by_id(agent_id)  # Only for global resources
```

### Testing
- `tests/db/test_tenant_isolation.py` verifies cross-organization access is blocked
- Tests cover all organization-scoped entities

## Transaction Management

### Rules
1. **Never** hold DB transaction during external calls (LLM, HTTP, browser)
2. Use short-lived transactions for DB operations only
3. Session per request via FastAPI dependency injection
4. Automatic rollback on exceptions

### Session Pattern
```python
async def get_db() -> AsyncSession:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
```

## Security

### Credential Storage
- **Never** store plaintext secrets in database
- `credentials.encrypted_data` — encrypted via application-layer encryption
- `api_keys.key_hash` — bcrypt/argon2 hash of full key
- `api_keys.key_prefix` — first 8-12 chars for identification
- `webhooks.secret_hash` — hash of webhook secret

### Key Management
- Encryption keys managed via environment variables
- Key rotation supported via key versioning in `encrypted_data`
- See Security phase for KMS integration

## Migrations

### Commands
```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Show current revision
alembic current

# Show history
alembic history
```

### Migration Files
- `001_initial.py` — Core identity tables (users, orgs, memberships, sessions, api_keys)
- `002_add_all_domain_models.py` — All domain models (agents, workflows, executions, tools, credentials, integrations, MCP, memory, conversations, approvals, evaluations, audit, webhooks)
- `018_add_approvals.py` — Approval satellite tables (MP19)
- `019_add_evaluator.py` — Evaluator tables + `evaluations` MP20 columns (MP20)

## Development Setup

### Local Database
```bash
# Start PostgreSQL + Redis
docker-compose up -d postgres redis

# Run migrations
cd apps/api
alembic upgrade head

# Run tests
pytest tests/db/ -v
```

### Seed Data
```bash
# Development seed (run after migrations)
python -m scripts.seed_dev
```

## Backup Considerations

### Critical Tables (High Priority)
- `users`, `organizations`, `memberships` — identity
- `credentials` — encrypted secrets
- `api_keys` — hashed keys
- `audit_logs` — compliance

### Large Tables (Consider Partitioning)
- `execution_events` — high volume, time-series
- `audit_logs` — high volume, append-only
- `workflow_executions` — execution history

### Retention
- `execution_events`: 90 days (configurable)
- `audit_logs`: 7 years (compliance)
- `task` results: 30 days

## Performance Baselines

| Operation | Target |
|-----------|--------|
| Simple PK lookup | < 5ms |
| Organization-scoped list (20 items) | < 20ms |
| Complex join (agent + versions + runs) | < 50ms |
| Audit log insert | < 10ms |
| Event insert (batch) | < 20ms |

## Future Extensions

### pgvector Integration
```sql
-- Enable extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Add vector index (when needed)
CREATE INDEX ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

### Partitioning
```sql
-- Partition execution_events by month
CREATE TABLE execution_events_2024_01 PARTITION OF execution_events
FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
```

### Read Replicas
- Configure async replicas for read-heavy queries (audit logs, events)
- Use `session.execute(query.execution_options(sync_session=False))` for replica routing

## Files

```
apps/api/
├── alembic/
│   ├── env.py
│   ├── versions/
│   │   ├── 001_initial.py
│   │   └── 002_add_all_domain_models.py
│   └── alembic.ini
├── src/openagent/db/
│   ├── session.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── user.py
│   │   ├── organization.py
│   │   ├── membership.py
│   │   ├── agent.py
│   │   ├── workflow.py
│   │   ├── workflow_execution.py
│   │   ├── task.py
│   │   ├── agent_run.py
│   │   ├── execution_event.py
│   │   ├── tool.py
│   │   ├── credential.py
│   │   ├── integration.py
│   │   ├── mcp_server.py
│   │   ├── memory.py
│   │   ├── conversation.py
│   │   ├── approval.py
│   │   ├── evaluation.py
│   │   ├── audit_log.py
│   │   ├── api_key.py
│   │   ├── webhook.py
│   │   └── session.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── user.py
│   │   ├── organization.py
│   │   ├── membership.py
│   │   ├── agent.py
│   │   ├── workflow.py
│   │   ├── task.py
│   │   ├── agent_run.py
│   │   ├── credential.py
│   │   ├── memory.py
│   │   ├── audit.py
│   │   └── webhook.py
│   ├── pagination.py
│   └── __init__.py
└── tests/db/
    ├── conftest.py
    ├── test_models.py
    ├── test_tenant_isolation.py
    └── test_pagination.py
```

## Next Phase

**MASTER PROMPT 03 — Authentication, Master Account & Identity System**

Will implement:
- Password hashing & verification
- JWT/OAuth token management
- Master account / superadmin
- Email verification flow
- Password reset
- Session management
- MFA support