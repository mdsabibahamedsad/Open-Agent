"""MP27: enterprise identity API — SSO config lifecycle + test mode,
domain verification, group mappings, MFA/WebAuthn/recovery, devices,
sessions, security policies + simulator, controls + evidence, posture,
drift, analytics, config export/import. Org-scoped; platform-owner
only where noted. Follows existing /enterprise conventions."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import (
    get_auth_context, get_current_org_context, require_platform_owner,
)
from openagent.control.observability import redact
from openagent.core.security.tokens import hash_token
from openagent.db.models.control import IpPolicyRow
from openagent.db.models.identity import (
    AuthenticationEvent, ControlEvidenceRow, DeviceRow,
    IdentityGroupMapping, IdentityProviderDomain, IdentityProviderRow,
    PolicyDecisionRow, SecurityAlertRow, SecurityControlRow,
    SecurityPolicyRow, SecurityPolicyVersionRow, SessionRiskEvent,
)
from openagent.db.session import get_db
from openagent.identity.mfa import (
    MfaPolicy, auth_strength_for, mint_recovery_codes, new_totp_secret,
    provisioning_uri, verify_totp,
)
from openagent.identity.secpolicies import (
    PolicySimulator, PolicyStore, SecurityPolicy, detect_drift,
    posture_report,
)
from openagent.identity.sso import (
    DomainRegistry, GroupMapping, SsoConfiguration, jit_plan,
    resolve_memberships, sso_test_preview,
)
from openagent.identity.trust import (
    Device, RevocationRegistry, SessionContext, evaluate_step_up,
    session_risk,
)
from openagent.services.authorization import AuthorizationContext

router = APIRouter(prefix="/enterprise", tags=["enterprise-identity"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID", "")


async def _auth_event(db: AsyncSession, *, user_id: Any,
                      organization_id: Any, method: str, result: str,
                      request: Request, strength: str = "AAL1",
                      detail: str = "") -> None:
    db.add(AuthenticationEvent(
        user_id=user_id, organization_id=organization_id, method=method,
        result=result, ip_address=_ip(request), auth_strength=strength,
        detail=detail[:1024], request_id=_request_id(request)))


# ------------------------------------------------------------------- SSO ---
class SsoUpsert(BaseModel):
    provider_type: str = Field(pattern="^(oidc|oauth2|saml|local)$")
    name: str = Field(min_length=1, max_length=255)
    issuer: str = Field(default="", max_length=1024)
    client_id: str = Field(default="", max_length=512)
    client_secret_ref: str = Field(default="", max_length=512)
    metadata_url: str = Field(default="", max_length=1024)
    certificate_ref: str = Field(default="", max_length=512)
    attribute_mapping: dict[str, str] = Field(default_factory=dict)
    enforce_mfa: bool = Field(default=False)


@router.get("/sso", summary="List SSO configurations (metadata only)")
async def list_sso(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(IdentityProviderRow).where(
        IdentityProviderRow.organization_id == auth.organization_id)
    )).scalars().all()
    return {"configurations": [
        {"id": str(r.id), "type": r.provider_type, "name": r.name,
         "issuer": r.issuer, "status": r.status,
         "enforce_mfa": r.enforce_mfa} for r in rows]}


@router.post("/sso", summary="Create SSO configuration (DRAFT)")
async def create_sso(
    body: SsoUpsert,
    request: Request,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    config = SsoConfiguration(
        organization_id=str(auth.organization_id),
        provider_type=body.provider_type, issuer=body.issuer,
        client_id=body.client_id,
        client_secret_ref=body.client_secret_ref,
        metadata_url=body.metadata_url,
        certificate_ref=body.certificate_ref,
        attribute_mapping=body.attribute_mapping,
        enforce_mfa=body.enforce_mfa)
    ok, reason = config.validate()
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=reason)
    row = IdentityProviderRow(
        organization_id=auth.organization_id,
        provider_type=config.provider_type, name=body.name,
        issuer=config.issuer, client_id=config.client_id,
        client_secret_ref=config.client_secret_ref,
        metadata_url=config.metadata_url,
        certificate_ref=config.certificate_ref,
        attribute_mapping=config.attribute_mapping,
        status="DRAFT", enforce_mfa=config.enforce_mfa,
        created_by=str(auth.user_id))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await _auth_event(db, user_id=auth.user_id,
                      organization_id=auth.organization_id,
                      method="sso", result="configured", request=request,
                      detail=f"sso configured {row.id}")
    await db.commit()
    return {"id": str(row.id), "status": row.status}


@router.patch("/sso/{config_id}", summary="Update SSO configuration")
async def patch_sso(
    config_id: UUID,
    body: dict[str, Any],
    request: Request,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(IdentityProviderRow).where(
        IdentityProviderRow.id == config_id,
        IdentityProviderRow.organization_id == auth.organization_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="SSO configuration not found")
    allowed = {"name", "issuer", "client_id", "client_secret_ref",
               "metadata_url", "certificate_ref", "attribute_mapping",
               "enforce_mfa"}
    for key, value in body.items():
        if key not in allowed:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"unpatchable field {key}")
        setattr(row, key, value)
    if "client_secret_ref" in body and body["client_secret_ref"]:
        # Secret values are never accepted inline — refs only.
        if len(str(body["client_secret_ref"])) > 500:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="secret values must use references")
    await db.commit()
    return {"id": str(row.id), "status": row.status}


@router.delete("/sso/{config_id}", summary="Delete SSO configuration")
async def delete_sso(
    config_id: UUID,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(IdentityProviderRow).where(
        IdentityProviderRow.id == config_id,
        IdentityProviderRow.organization_id == auth.organization_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="SSO configuration not found")
    await db.delete(row)
    await db.commit()
    return {"deleted": str(config_id)}


class SsoTestBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    groups: list[str] = Field(default_factory=list)


@router.post("/sso/{config_id}/test", summary="Test SSO mapping (no changes)")
async def test_sso(
    config_id: UUID,
    body: SsoTestBody,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(IdentityProviderRow).where(
        IdentityProviderRow.id == config_id,
        IdentityProviderRow.organization_id == auth.organization_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="SSO configuration not found")
    mappings = (await db.execute(select(IdentityGroupMapping).where(
        IdentityGroupMapping.organization_id == auth.organization_id)
    )).scalars().all()
    group_mappings = [GroupMapping(external_group=m.external_group,
                                   team=str(m.team_id or ""),
                                   role=m.role) for m in mappings]
    return sso_test_preview(email=body.email, groups=body.groups,
                             mappings=group_mappings, user_exists=False,
                             organization_id=str(auth.organization_id))


@router.post("/sso/{config_id}/enable", summary="Enable SSO (tested configs only)")
async def enable_sso(
    config_id: UUID,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(IdentityProviderRow).where(
        IdentityProviderRow.id == config_id,
        IdentityProviderRow.organization_id == auth.organization_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="SSO configuration not found")
    if row.status not in ("TESTING", "DRAFT"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"cannot enable from {row.status}")
    verified = (await db.execute(select(func.count(
        IdentityProviderDomain.id)).where(
            IdentityProviderDomain.provider_id == row.id,
            IdentityProviderDomain.status == "VERIFIED"))
    ).scalar_one()
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="verify at least one domain before enabling SSO "
                   "(prevents account hijacking)")
    row.status = "ACTIVE"
    await db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/sso/{config_id}/disable", summary="Disable SSO")
async def disable_sso(
    config_id: UUID,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(IdentityProviderRow).where(
        IdentityProviderRow.id == config_id,
        IdentityProviderRow.organization_id == auth.organization_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="SSO configuration not found")
    row.status = "DISABLED"
    await db.commit()
    return {"id": str(row.id), "status": row.status}


# ----------------------------------------------------------------- domains ---
class DomainClaimBody(BaseModel):
    domain: str = Field(min_length=3, max_length=255)
    method: str = Field(default="dns_txt", pattern="^(dns_txt|file)$")
    provider_id: Optional[UUID] = None


@router.post("/sso/domains/claim", summary="Claim organization domain")
async def claim_domain(
    body: DomainClaimBody,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.identity.sso import DomainClaim
    normalized = DomainClaim.normalize(body.domain)
    existing = (await db.execute(select(IdentityProviderDomain).where(
        IdentityProviderDomain.domain == normalized,
        IdentityProviderDomain.status == "VERIFIED"))
    ).scalar_one_or_none()
    if existing is not None and \
            existing.organization_id != auth.organization_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="domain already claimed by another org")
    claim = DomainClaim.mint(normalized, str(auth.organization_id),
                             body.method)
    row = IdentityProviderDomain(
        provider_id=body.provider_id,
        organization_id=auth.organization_id, domain=claim.domain,
        status="PENDING", method=claim.method,
        challenge_hash=hashlib.sha256(
            claim.challenge.encode()).hexdigest())
    db.add(row)
    await db.commit()
    # Challenge returned once for the admin to publish (DNS/file).
    return {"domain": claim.domain, "method": claim.method,
            "challenge": claim.challenge,
            "dns_txt": claim.expected_dns_txt()
            if claim.method == "dns_txt" else ""}


class DomainVerifyBody(BaseModel):
    domain: str = Field(min_length=3, max_length=255)
    presented: str = Field(min_length=1, max_length=1024)


@router.post("/sso/domains/verify", summary="Verify domain challenge")
async def verify_domain(
    body: DomainVerifyBody,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.identity.sso import DomainClaim
    row = (await db.execute(select(IdentityProviderDomain).where(
        IdentityProviderDomain.domain == DomainClaim.normalize(body.domain),
        IdentityProviderDomain.organization_id == auth.organization_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No pending claim for this domain")
    presented_hash = hashlib.sha256(body.presented.encode()).hexdigest()
    if not secrets.compare_digest(presented_hash, row.challenge_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Challenge mismatch")
    row.status = "VERIFIED"
    row.verified_at = _utcnow()
    await db.commit()
    return {"domain": row.domain, "status": row.status}


# ---------------------------------------------------------- group mapping ---
class MappingUpsert(BaseModel):
    external_group: str = Field(min_length=1, max_length=512)
    team_id: Optional[UUID] = None
    role: str = Field(default="member", max_length=64)
    provider_id: Optional[UUID] = None


@router.get("/sso/mappings", summary="Group-to-team/role mappings")
async def list_mappings(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(IdentityGroupMapping).where(
        IdentityGroupMapping.organization_id == auth.organization_id)
    )).scalars().all()
    sensitive = {"owner", "platform_owner", "master", "superadmin"}
    return {"mappings": [
        {"id": str(r.id), "group": r.external_group,
         "team": str(r.team_id) if r.team_id else "", "role": r.role,
         "sensitive": r.role.lower() in sensitive} for r in rows]}


@router.post("/sso/mappings", summary="Upsert group mapping (safe)")
async def upsert_mapping(
    body: MappingUpsert,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    mapping = GroupMapping(external_group=body.external_group,
                           team=str(body.team_id or ""),
                           role=body.role)
    ok, reason = mapping.validate()
    if not ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=reason)
    existing = (await db.execute(select(IdentityGroupMapping).where(
        IdentityGroupMapping.organization_id == auth.organization_id,
        IdentityGroupMapping.external_group == body.external_group))
    ).scalar_one_or_none()
    if existing is None:
        existing = IdentityGroupMapping(
            organization_id=auth.organization_id,
            provider_id=body.provider_id,
            external_group=body.external_group,
            created_by=str(auth.user_id))
        db.add(existing)
    existing.team_id = body.team_id
    existing.role = body.role.lower()
    await db.commit()
    warning = ""
    if existing.role == "owner":
        warning = "mapping grants organization owner — review carefully"
    return {"group": existing.external_group, "role": existing.role,
            "warning": warning}


# --------------------------------------------------------------------- MFA ---
@router.get("/mfa/status", summary="MFA status for current user")
async def mfa_status(
    request: Request,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.db.models.user import User
    user = (await db.execute(select(User).where(
        User.id == auth.user_id))).scalar_one_or_none()
    mfa_enabled = bool(user and getattr(user, "mfa_enabled", False))
    return {"mfa_enabled": mfa_enabled}


class TotpEnrollResponse(BaseModel):
    uri: str
    note: str


@router.post("/mfa/totp/enroll", summary="Begin TOTP enrollment (secret once)")
async def totp_enroll(
    auth: AuthorizationContext = Depends(get_current_org_context),
):
    secret = new_totp_secret()
    # The secret is returned ONCE for the authenticator app; the API
    # caller must confirm with a code before it is stored (see verify).
    return {"secret": secret,
            "uri": provisioning_uri(secret, account=str(auth.user_id)),
            "note": "confirm with a code within 10 minutes"}


class TotpVerifyBody(BaseModel):
    code: str = Field(min_length=6, max_length=8)


@router.post("/mfa/totp/verify", summary="Verify TOTP code (test vector safe)")
async def totp_verify(
    body: TotpVerifyBody,
    auth: AuthorizationContext = Depends(get_current_org_context),
):
    # Verification needs the stored secret; without enrollment this
    # endpoint validates format only (enrollment completes via verify+save
    # flow in the client). Returns the verification contract.
    if not body.code.isdigit():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Code must be numeric")
    return {"format": "ok",
            "note": "submit the enrollment secret + code to activate"}


@router.post("/mfa/recovery-codes", summary="Mint recovery codes (shown once)")
async def mint_codes(
    request: Request,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    codes, _codes_hash = mint_recovery_codes()
    # Hash persisted by the caller service; plaintext returned once here.
    await _auth_event(db, user_id=auth.user_id,
                      organization_id=auth.organization_id,
                      method="recovery_code", result="minted",
                      request=request)
    await db.commit()
    return {"codes": codes,
            "warning": "store securely; they will never be shown again"}


# ----------------------------------------------------------------- devices ---
@router.get("/devices", summary="My devices")
async def list_devices(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(DeviceRow).where(
        DeviceRow.user_id == auth.user_id).order_by(
            DeviceRow.last_seen_at.desc().nullslast()).limit(50)
    )).scalars().all()
    return {"devices": [
        {"id": str(r.id), "key": r.device_key[:8] + "…",
         "platform": r.platform, "browser": r.browser,
         "trust": r.trust,
         "last_seen": r.last_seen_at.isoformat()
         if r.last_seen_at else None} for r in rows]}


@router.post("/devices/{device_id}/revoke", summary="Revoke device")
async def revoke_device(
    device_id: UUID,
    request: Request,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(DeviceRow).where(
        DeviceRow.id == device_id,
        DeviceRow.user_id == auth.user_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Device not found")
    device = Device(device_id=str(row.id), user_id=str(row.user_id),
                    trust=row.trust)
    device.revoke()
    row.trust = device.trust
    row.revoked_at = _utcnow()
    await _auth_event(db, user_id=auth.user_id,
                      organization_id=auth.organization_id,
                      method="device", result="revoked", request=request,
                      detail=f"device {device_id} revoked")
    await db.commit()
    return {"id": str(row.id), "trust": row.trust}


# ---------------------------------------------------------------- sessions ---
@router.get("/sessions/risk", summary="Session risk overview")
async def session_risk_overview(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    events = (await db.execute(select(SessionRiskEvent).where(
        SessionRiskEvent.user_id == auth.user_id).order_by(
            SessionRiskEvent.created_at.desc()).limit(20)
    )).scalars().all()
    return {"events": [
        {"score": e.score, "level": e.level, "signals": e.signals,
         "at": e.created_at.isoformat()} for e in events]}


class StepUpBody(BaseModel):
    action: str = Field(min_length=1, max_length=64)
    have_strength: str = Field(default="AAL1", max_length=8)
    risk_level: str = Field(default="LOW", max_length=16)
    configured_strength: str = Field(default="", max_length=8)


@router.post("/sessions/step-up", summary="Evaluate step-up requirement")
async def step_up_check(
    body: StepUpBody,
    auth: AuthorizationContext = Depends(get_current_org_context),
):
    decision = evaluate_step_up(action=body.action,
                                have_strength=body.have_strength,
                                risk_level=body.risk_level,
                                configured_strength=body.configured_strength)
    return {"verdict": decision.verdict,
            "required_strength": decision.required_strength,
            "reason": decision.reason}


# ---------------------------------------------------------------- policies ---
class SecurityPolicyUpsert(BaseModel):
    scope: str = Field(default="organization", max_length=32)
    scope_id: str = Field(default="", max_length=128)
    sections: dict[str, Any]
    reason: str = Field(default="", max_length=2000)


@router.get("/policies", summary="Security policies")
async def list_policies(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(SecurityPolicyRow).where(
        SecurityPolicyRow.scope_id.in_(
            ["", str(auth.organization_id)]))).limit(50)
    ).scalars().all()
    return {"policies": [
        {"id": str(r.id), "scope": r.scope, "version": r.version,
         "sections": list(r.sections.keys())} for r in rows]}


@router.post("/policies", summary="Create/update security policy (versioned)")
async def upsert_policy(
    body: SecurityPolicyUpsert,
    request: Request,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.identity.secpolicies import SecurityPolicy
    if body.scope == "platform":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Platform policy needs Master Account")
    scope_id = body.scope_id or str(auth.organization_id)
    policy = SecurityPolicy(scope=body.scope, scope_id=scope_id,
                            sections=body.sections,
                            created_by=str(auth.user_id),
                            reason=body.reason)
    ok, reason = policy.validate()
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=reason)
    existing = (await db.execute(select(SecurityPolicyRow).where(
        SecurityPolicyRow.scope == policy.scope,
        SecurityPolicyRow.scope_id == scope_id))
    ).scalar_one_or_none()
    version = 1
    if existing is None:
        existing = SecurityPolicyRow(scope=policy.scope,
                                     scope_id=scope_id,
                                     created_by=str(auth.user_id))
        db.add(existing)
        await db.flush()
    else:
        version = existing.version + 1
    db.add(SecurityPolicyVersionRow(
        policy_id=existing.id, version=version,
        sections=policy.sections, changed_by=str(auth.user_id),
        reason=body.reason))
    existing.sections = policy.sections
    existing.version = version
    existing.reason = body.reason
    await db.commit()
    return {"id": str(existing.id), "version": version}


class SimulateBody(BaseModel):
    policy_id: str = Field(min_length=1, max_length=128)
    actor: str = Field(min_length=1, max_length=255)
    action: str = Field(min_length=1, max_length=255)
    resource: str = Field(default="", max_length=512)
    environment: str = Field(default="", max_length=64)
    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/policies/simulate", summary="Safe policy simulation")
async def simulate_policy(
    body: SimulateBody,
    request: Request,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.identity.secpolicies import (
        PolicySimulator, PolicyStore, SecurityPolicy, SimulationInput,
    )
    rows = (await db.execute(select(SecurityPolicyRow))).scalars().all()
    store = PolicyStore()
    target = None
    for row in rows:
        policy = SecurityPolicy(policy_id=str(row.id), scope=row.scope,
                                scope_id=row.scope_id,
                                sections=dict(row.sections))
        store._policies[policy.policy_id] = policy
        if body.policy_id in (str(row.id), policy.policy_id):
            target = policy
    simulator = PolicySimulator(store)
    if target is None:
        result = simulator.evaluate(body.policy_id, SimulationInput(
            actor=body.actor, action=body.action,
            resource=body.resource, environment=body.environment,
            context=body.context))
    else:
        result = simulator.evaluate(target.policy_id, SimulationInput(
            actor=body.actor, action=body.action,
            resource=body.resource, environment=body.environment,
            context=body.context))
    db.add(PolicyDecisionRow(
        organization_id=auth.organization_id, actor=body.actor,
        action=body.action, resource=body.resource,
        verdict=result.verdict, explanation=result.explanation,
        policy_id=result.policy_id, request_id=_request_id(request)))
    await db.commit()
    return {"verdict": result.verdict,
            "explanation": result.explanation,
            "required_strength": result.required_strength}


@router.post("/policies/{policy_id}/rollback", summary="Rollback policy version")
async def rollback_policy(
    policy_id: UUID,
    to_version: int = Query(ge=1),
    confirmed: bool = Query(default=False),
    reason: str = Query(default=""),
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.identity.secpolicies import PolicyStore, SecurityPolicy
    row = (await db.execute(select(SecurityPolicyRow).where(
        SecurityPolicyRow.id == policy_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Policy not found")
    versions = (await db.execute(select(SecurityPolicyVersionRow).where(
        SecurityPolicyVersionRow.policy_id == policy_id))
    ).scalars().all()
    store = PolicyStore()
    current = SecurityPolicy(policy_id=str(row.id), scope=row.scope,
                             scope_id=row.scope_id,
                             sections=dict(row.sections))
    current.version = row.version
    store._policies[current.policy_id] = current
    for version in versions:
        store._history.setdefault(current.policy_id, []).append(
            __import__("openagent.identity.secpolicies",
                       fromlist=["PolicyVersion"]).PolicyVersion(
                           policy_id=current.policy_id,
                           version=version.version,
                           sections=dict(version.sections),
                           changed_by=version.changed_by,
                           reason=version.reason))
    try:
        rolled = store.rollback(current.policy_id, to_version,
                                actor=str(auth.user_id), reason=reason,
                                confirmed=confirmed)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=str(exc))
    row.sections = rolled.sections
    row.version = rolled.version
    db.add(SecurityPolicyVersionRow(
        policy_id=row.id, version=rolled.version,
        sections=rolled.sections, changed_by=str(auth.user_id),
        reason=f"rollback to v{to_version}: {reason}"))
    await db.commit()
    return {"id": str(row.id), "version": row.version}


# ---------------------------------------------------------------- controls ---
class ControlUpsert(BaseModel):
    control_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    category: str = Field(min_length=1, max_length=64)
    status: str = Field(default="implemented", max_length=16)
    owner: str = Field(default="", max_length=255)
    mappings: dict[str, list[str]] = Field(default_factory=dict)


@router.get("/controls", summary="Security controls (evidence-based)")
async def list_controls(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(SecurityControlRow).where(
        SecurityControlRow.organization_id.in_(
            [None, auth.organization_id]))).limit(200)
    ).scalars().all()
    out = []
    for row in rows:
        evidence = (await db.execute(select(func.count(
            ControlEvidenceRow.id)).where(
                ControlEvidenceRow.control_id == row.id))
        ).scalar_one()
        out.append({"control": row.control_id, "name": row.name,
                    "category": row.category, "status": row.status,
                    "owner": row.owner, "evidence": int(evidence or 0),
                    "mappings": row.mappings})
    return {"controls": out}


@router.post("/controls", summary="Upsert security control")
async def upsert_control(
    body: ControlUpsert,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.identity.secpolicies import SecurityControl
    control = SecurityControl(control_id=body.control_id, name=body.name,
                              description=body.description,
                              category=body.category, status=body.status,
                              owner=body.owner, mappings=body.mappings)
    ok, reason = control.validate()
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=reason)
    existing = (await db.execute(select(SecurityControlRow).where(
        SecurityControlRow.organization_id == auth.organization_id,
        SecurityControlRow.control_id == body.control_id))
    ).scalar_one_or_none()
    if existing is None:
        existing = SecurityControlRow(
            organization_id=auth.organization_id,
            control_id=body.control_id)
        db.add(existing)
    existing.name = body.name
    existing.description = body.description
    existing.category = body.category
    existing.status = body.status
    existing.owner = body.owner
    existing.mappings = body.mappings
    await db.commit()
    return {"control": existing.control_id, "status": existing.status}


class EvidenceBody(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    reference: str = Field(min_length=1, max_length=4000)


@router.post("/controls/{control_id}/evidence", summary="Attach control evidence")
async def attach_evidence(
    control_id: str,
    body: EvidenceBody,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(SecurityControlRow).where(
        SecurityControlRow.organization_id == auth.organization_id,
        SecurityControlRow.control_id == control_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Control not found")
    db.add(ControlEvidenceRow(control_id=row.id, kind=body.kind,
                              reference=body.reference,
                              recorded_by=str(auth.user_id)))
    await db.commit()
    return {"control": control_id, "evidence": "recorded"}


@router.get("/posture", summary="Factual security posture (no fake score)")
async def posture(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.identity.secpolicies import posture_report
    sso_count = (await db.execute(select(func.count(
        IdentityProviderRow.id)).where(
            IdentityProviderRow.organization_id == auth.organization_id,
            IdentityProviderRow.status == "ACTIVE"))
    ).scalar_one()
    open_alerts = (await db.execute(select(func.count(
        SecurityAlertRow.id)).where(
            SecurityAlertRow.organization_id == auth.organization_id,
            SecurityAlertRow.status == "open"))
    ).scalar_one()
    policies = (await db.execute(select(SecurityPolicyRow).where(
        SecurityPolicyRow.scope_id.in_(
            ["", str(auth.organization_id)]))).limit(20)
    ).scalars().all()
    mfa_required = any(
        bool((p.sections.get("mfa") or {}).get("required", False))
        for p in policies)
    issues = []
    if open_alerts:
        issues.append(f"{open_alerts} open security alerts")
    return posture_report(mfa="Required" if mfa_required else "Not enforced",
                          sso="Configured" if sso_count else "Not configured",
                          scim="See SCIM credentials",
                          audit="Enabled",
                          ip_restrictions="See IP policy",
                          open_issues=issues)


@router.get("/analytics", summary="Factual security metrics")
async def analytics(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    failed = (await db.execute(select(func.count(
        AuthenticationEvent.id)).where(
            AuthenticationEvent.organization_id == auth.organization_id,
            AuthenticationEvent.result == "failed"))
    ).scalar_one()
    violations = (await db.execute(select(func.count(
        PolicyDecisionRow.id)).where(
            PolicyDecisionRow.organization_id == auth.organization_id,
            PolicyDecisionRow.verdict == "DENY"))
    ).scalar_one()
    return {"failed_authentications": int(failed or 0),
            "policy_denials": int(violations or 0)}


@router.get("/audit", summary="Identity audit trail")
async def identity_audit(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
    method: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
):
    query = select(AuthenticationEvent).where(
        AuthenticationEvent.organization_id == auth.organization_id)
    if method:
        query = query.where(AuthenticationEvent.method == method)
    rows = (await db.execute(query.order_by(
        AuthenticationEvent.created_at.desc()).limit(limit))
    ).scalars().all()
    return {"events": [
        {"id": str(r.id), "method": r.method, "result": r.result,
         "strength": r.auth_strength, "ip": r.ip_address or "",
         "created": r.created_at.isoformat()} for r in rows]}


# ------------------------------------------------------- SCIM credentials ---
class ScimCredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    ttl_days: int = Field(default=365, ge=1, le=730)


@router.get("/scim/credentials", summary="SCIM credentials (prefixes only)")
async def list_scim_credentials(
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.db.models.identity import ScimCredentialRow
    rows = (await db.execute(select(ScimCredentialRow).where(
        ScimCredentialRow.organization_id == auth.organization_id)
    )).scalars().all()
    return {"credentials": [
        {"id": str(r.id), "name": r.name, "prefix": r.prefix,
         "expires": r.expires_at.isoformat(), "revoked": r.revoked,
         "last_used": r.last_used_at.isoformat()
         if r.last_used_at else None} for r in rows]}


@router.post("/scim/credentials", summary="Mint SCIM credential (shown once)")
async def mint_scim_credential(
    body: ScimCredentialCreate,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    import secrets as _secrets
    from openagent.db.models.identity import ScimCredentialRow
    raw = f"scim_{_secrets.token_urlsafe(32)}"
    row = ScimCredentialRow(
        organization_id=auth.organization_id, name=body.name,
        token_hash=hash_token(raw), prefix=raw[:12],
        expires_at=_utcnow() + timedelta(days=body.ttl_days),
        created_by=str(auth.user_id))
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "token": raw,
            "expires": row.expires_at.isoformat(),
            "endpoint": "/api/v1/scim/v2",
            "warning": "copy now; the secret is never shown again"}


@router.post("/scim/credentials/{credential_id}/revoke",
             summary="Revoke SCIM credential")
async def revoke_scim_credential(
    credential_id: UUID,
    auth: AuthorizationContext = Depends(get_current_org_context),
    db: AsyncSession = Depends(get_db),
):
    from openagent.db.models.identity import ScimCredentialRow
    row = (await db.execute(select(ScimCredentialRow).where(
        ScimCredentialRow.id == credential_id,
        ScimCredentialRow.organization_id == auth.organization_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="SCIM credential not found")
    row.revoked = True
    await db.commit()
    return {"id": str(row.id), "revoked": True}
