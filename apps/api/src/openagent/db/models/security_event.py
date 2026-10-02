import uuid
from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, JSON, ForeignKey, Index, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from openagent.db.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from openagent.db.models.user import User
    from openagent.db.models.organization import Organization


class SecurityEventType(str, enum.Enum):
    LOGIN_SUCCESS = "login.success"
    LOGIN_FAILED = "login.failed"
    LOGOUT = "logout"
    LOGOUT_ALL = "logout.all"
    PASSWORD_CHANGED = "password.changed"
    PASSWORD_RESET_REQUESTED = "password.reset.requested"
    PASSWORD_RESET_COMPLETED = "password.reset.completed"
    EMAIL_VERIFICATION_COMPLETED = "email.verification.completed"
    SESSION_REVOKED = "session.revoked"
    ACCOUNT_SUSPENDED = "account.suspended"
    ACCOUNT_UNSUSPENDED = "account.unsuspended"
    MASTER_LOGIN = "master.login"
    MASTER_SESSION_CREATED = "master.session.created"
    MASTER_SESSION_REVOKED = "master.session.revoked"
    MFA_ENABLED = "mfa.enabled"
    MFA_DISABLED = "mfa.disabled"
    REGISTRATION = "registration"
    EMAIL_VERIFICATION_SENT = "email.verification.sent"
    PASSWORD_RESET_EMAIL_SENT = "password.reset.email.sent"
    APPROVAL_SELF_APPROVAL_ATTEMPT = "approval.self_approval_attempt"
    APPROVAL_REPLAY_ATTEMPT = "approval.replay_attempt"
    APPROVAL_EXPIRED_EXECUTION_ATTEMPT = "approval.expired_execution_attempt"
    APPROVAL_MODIFIED_PAYLOAD = "approval.modified_payload"
    APPROVAL_CROSS_TENANT_ATTEMPT = "approval.cross_tenant_attempt"
    APPROVAL_POLICY_BYPASS_ATTEMPT = "approval.policy_bypass_attempt"
    APPROVAL_PRIVILEGE_ESCALATION_ATTEMPT = "approval.privilege_escalation_attempt"
    EVALUATOR_MANIPULATION_ATTEMPT = "evaluator.manipulation_attempt"
    EVIDENCE_TAMPER_ATTEMPT = "evidence.tamper_attempt"
    EVALUATION_CROSS_TENANT_ATTEMPT = "evaluation.cross_tenant_attempt"
    EVALUATION_SELF_EVALUATION_ABUSE = "evaluation.self_evaluation_abuse"
    EVALUATION_SCORE_MANIPULATION = "evaluation.score_manipulation"
    CORRECTION_POLICY_BYPASS_ATTEMPT = "correction.policy_bypass_attempt"
    CORRECTION_LOOP_ABUSE = "correction.loop_abuse"
    CONNECTOR_CROSS_TENANT_ATTEMPT = "connector.cross_tenant_attempt"
    CONNECTOR_CREDENTIAL_FAILURE = "connector.credential_failure"
    CONNECTOR_WEBHOOK_FORGERY = "connector.webhook_forgery"
    CONNECTOR_WEBHOOK_REPLAY = "connector.webhook_replay"
    CONNECTOR_SIGNATURE_INVALID = "connector.signature_invalid"
    CONNECTOR_POLICY_BYPASS_ATTEMPT = "connector.policy_bypass_attempt"
    CONNECTOR_OAUTH_CSRF = "connector.oauth_csrf"
    CONNECTOR_TOKEN_REPLAY = "connector.token_replay"
    CONNECTOR_PRIVILEGE_ESCALATION_ATTEMPT = "connector.privilege_escalation_attempt"
    CONNECTOR_EXFILTRATION_ATTEMPT = "connector.exfiltration_attempt"
    CONNECTOR_UNUSUAL_USAGE = "connector.unusual_usage"


class SecurityEvent(TimestampMixin, UUIDMixin, Base):
    __tablename__ = "security_events"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[SecurityEventType] = mapped_column(
        SQLEnum(SecurityEventType, name="security_event_type", create_constraint=True),
        nullable=False, index=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    user: Mapped[Optional["User"]] = relationship()
    organization: Mapped[Optional["Organization"]] = relationship()

    __table_args__ = (
        Index("ix_security_events_user_id", "user_id"),
        Index("ix_security_events_organization_id", "organization_id"),
        Index("ix_security_events_event_type", "event_type"),
        Index("ix_security_events_created_at", "created_at"),
        Index("ix_security_events_request_id", "request_id"),
        Index("ix_security_events_user_created", "user_id", "created_at"),
        Index("ix_security_events_org_created", "organization_id", "created_at"),
    )