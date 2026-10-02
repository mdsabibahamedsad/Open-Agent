"""Browser automation SQLAlchemy models (mirrors alembic 015_add_browser_automation)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import JSON as SA_JSON
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from openagent.db.models.base import Base, TimestampMixin, SoftDeleteMixin, UUIDMixin


class BrowserProviderType(str, enum.Enum):
    playwright = "playwright"
    browserless = "browserless"
    remote_chromium = "remote_chromium"
    cloud_browser = "cloud_browser"
    custom = "custom"


class BrowserType(str, enum.Enum):
    chromium = "chromium"
    firefox = "firefox"
    webkit = "webkit"


class BrowserSessionStatus(str, enum.Enum):
    CREATED = "CREATED"
    STARTING = "STARTING"
    READY = "READY"
    BUSY = "BUSY"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class BrowserProfileType(str, enum.Enum):
    EPHEMERAL = "EPHEMERAL"
    PERSISTENT = "PERSISTENT"
    SHARED = "SHARED"
    ORGANIZATION = "ORGANIZATION"
    USER = "USER"


class BrowserPageStatus(str, enum.Enum):
    CREATED = "CREATED"
    LOADING = "LOADING"
    READY = "READY"
    CLOSED = "CLOSED"
    ERROR = "ERROR"


class BrowserActionType(str, enum.Enum):
    NAVIGATE = "NAVIGATE"
    CLICK = "CLICK"
    DOUBLE_CLICK = "DOUBLE_CLICK"
    TYPE = "TYPE"
    FILL = "FILL"
    SELECT = "SELECT"
    CHECK = "CHECK"
    UNCHECK = "UNCHECK"
    HOVER = "HOVER"
    SCROLL = "SCROLL"
    PRESS_KEY = "PRESS_KEY"
    DRAG = "DRAG"
    DROP = "DROP"
    WAIT = "WAIT"
    SCREENSHOT = "SCREENSHOT"
    EXTRACT = "EXTRACT"
    UPLOAD = "UPLOAD"
    DOWNLOAD = "DOWNLOAD"
    SWITCH_TAB = "SWITCH_TAB"
    GO_BACK = "GO_BACK"
    GO_FORWARD = "GO_FORWARD"
    RELOAD = "RELOAD"
    FOCUS = "FOCUS"
    EVALUATE = "EVALUATE"
    SET_VIEWPORT = "SET_VIEWPORT"
    SET_COOKIE = "SET_COOKIE"
    CLEAR_COOKIES = "CLEAR_COOKIES"
    GET_COOKIES = "GET_COOKIES"
    AUTHENTICATE = "AUTHENTICATE"
    HANDLE_DIALOG = "HANDLE_DIALOG"
    WAIT_FOR_SELECTOR = "WAIT_FOR_SELECTOR"
    WAIT_FOR_NAVIGATION = "WAIT_FOR_NAVIGATION"
    WAIT_FOR_FUNCTION = "WAIT_FOR_FUNCTION"
    SELECT_OPTION = "SELECT_OPTION"
    SET_INPUT_FILES = "SET_INPUT_FILES"
    CHECKBOX = "CHECKBOX"
    RADIO = "RADIO"


class BrowserActionRiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class BrowserTaskStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    PAUSED = "PAUSED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class BrowserDomainPolicyAction(str, enum.Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    CONFIRM = "CONFIRM"


class BrowserChallengeType(str, enum.Enum):
    CAPTCHA = "CAPTCHA"
    MFA_REQUIRED = "MFA_REQUIRED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    SECURITY_CHECK = "SECURITY_CHECK"
    BOT_CHALLENGE = "BOT_CHALLENGE"


class BrowserArtifactType(str, enum.Enum):
    screenshot = "screenshot"
    download = "download"
    extraction = "extraction"
    html = "html"
    har = "har"
    video = "video"
    trace = "trace"


class BrowserProfile(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "browser_profiles"

    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    browser_type: Mapped[BrowserType] = mapped_column(SQLEnum(BrowserType, name="browser_type", create_constraint=False), default=BrowserType.chromium, nullable=False)
    profile_type: Mapped[BrowserProfileType] = mapped_column(SQLEnum(BrowserProfileType, name="browser_profile_type", create_constraint=False), default=BrowserProfileType.EPHEMERAL, nullable=False)
    storage_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(SA_JSON, nullable=True)
    policy: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class BrowserSession(TimestampMixin, SoftDeleteMixin, UUIDMixin, Base):
    __tablename__ = "browser_sessions"

    session_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    workflow_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workflow_executions.id", ondelete="SET NULL"), nullable=True)
    browser_profile_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_profiles.id", ondelete="SET NULL"), nullable=True)
    provider: Mapped[BrowserProviderType] = mapped_column(SQLEnum(BrowserProviderType, name="browser_provider_type", create_constraint=False), default=BrowserProviderType.playwright, nullable=False)
    provider_config: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    status: Mapped[BrowserSessionStatus] = mapped_column(SQLEnum(BrowserSessionStatus, name="browser_session_status", create_constraint=False), default=BrowserSessionStatus.CREATED, nullable=False, index=True)
    headless: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)


class BrowserContext(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "browser_contexts"

    context_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    cookies: Mapped[List[Any]] = mapped_column(SA_JSON, default=list, nullable=False)
    local_storage: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    session_storage: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    permissions: Mapped[List[Any]] = mapped_column(SA_JSON, default=list, nullable=False)
    locale: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    timezone_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    viewport: Mapped[Optional[Dict[str, Any]]] = mapped_column(SA_JSON, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    proxy: Mapped[Optional[Dict[str, Any]]] = mapped_column(SA_JSON, nullable=True)
    offline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    storage_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(SA_JSON, nullable=True)


class BrowserPage(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "browser_pages"

    page_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    context_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_contexts.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[BrowserPageStatus] = mapped_column(SQLEnum(BrowserPageStatus, name="browser_page_status", create_constraint=False), default=BrowserPageStatus.CREATED, nullable=False)
    is_popup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opener_page_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_pages.id", ondelete="SET NULL"), nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BrowserTask(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "browser_tasks"

    task_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    workflow_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workflow_executions.id", ondelete="SET NULL"), nullable=True)
    browser_session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[BrowserTaskStatus] = mapped_column(SQLEnum(BrowserTaskStatus, name="browser_task_status", create_constraint=False), default=BrowserTaskStatus.QUEUED, nullable=False, index=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    current_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_page_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_pages.id", ondelete="SET NULL"), nullable=True)
    current_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_steps: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    timeout: Mapped[int] = mapped_column(Integer, default=300000, nullable=False)
    risk_policy: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)


class BrowserAction(UUIDMixin, Base):
    __tablename__ = "browser_actions"

    action_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    page_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[BrowserActionType] = mapped_column(SQLEnum(BrowserActionType, name="browser_action_type", create_constraint=False), nullable=False)
    input: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    risk_level: Mapped[BrowserActionRiskLevel] = mapped_column(SQLEnum(BrowserActionRiskLevel, name="browser_action_risk_level", create_constraint=False), default=BrowserActionRiskLevel.MEDIUM, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(SA_JSON, nullable=True)
    error: Mapped[Optional[Dict[str, Any]]] = mapped_column(SA_JSON, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BrowserObservation(UUIDMixin, Base):
    __tablename__ = "browser_observations"

    task_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    action_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_actions.id", ondelete="SET NULL"), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    viewport: Mapped[Optional[Dict[str, Any]]] = mapped_column(SA_JSON, nullable=True)
    scroll_position: Mapped[Optional[Dict[str, Any]]] = mapped_column(SA_JSON, nullable=True)
    interactive_elements: Mapped[List[Any]] = mapped_column(SA_JSON, default=list, nullable=False)
    text_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dom_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    screenshot_ref: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    accessibility_tree: Mapped[Optional[Dict[str, Any]]] = mapped_column(SA_JSON, nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BrowserArtifact(UUIDMixin, Base):
    __tablename__ = "browser_artifacts"

    artifact_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_tasks.id", ondelete="SET NULL"), nullable=True)
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[BrowserArtifactType] = mapped_column(SQLEnum(BrowserArtifactType, name="browser_artifact_type", create_constraint=False), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class BrowserEvent(UUIDMixin, Base):
    __tablename__ = "browser_events"

    event_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="SET NULL"), nullable=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_tasks.id", ondelete="SET NULL"), nullable=True)
    page_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_pages.id", ondelete="SET NULL"), nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(SA_JSON, default=dict, nullable=False)
    meta: Mapped[Dict[str, Any]] = mapped_column("metadata", SA_JSON, default=dict, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class BrowserDomainPolicy(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "browser_domain_policies"

    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    agent_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True)
    workflow_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True)
    browser_profile_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_profiles.id", ondelete="CASCADE"), nullable=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_tasks.id", ondelete="CASCADE"), nullable=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    action: Mapped[BrowserDomainPolicyAction] = mapped_column(SQLEnum(BrowserDomainPolicyAction, name="browser_domain_policy_action", create_constraint=False), default=BrowserDomainPolicyAction.ALLOW, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class BrowserSessionLease(UUIDMixin, Base):
    __tablename__ = "browser_session_leases"

    lease_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    holder_id: Mapped[str] = mapped_column(String(100), nullable=False)
    holder_type: Mapped[str] = mapped_column(String(20), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(255), nullable=False)


class BrowserStateFingerprint(UUIDMixin, Base):
    __tablename__ = "browser_state_fingerprints"

    task_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("browser_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dom_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    interactive_elements_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
