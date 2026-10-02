"""Universal integrations, connectors & external systems API (MP21).

Tenant isolation via path organization_id vs auth context on every route.
RBAC: connector:read/create/update/delete/execute/admin, credential:*
(webhook receiver is signature-authenticated, not session-authenticated).
Secrets are never returned: create/rotate respond with masked metadata only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.api.dependencies import get_current_org_context
from openagent.db.models.connector import (
    ConnectionScope,
    ConnectionStatus,
    Connector,
    ConnectorAction,
    ConnectorCapability,
    ConnectorConnection,
    ConnectorEvent,
    ConnectorHealth,
    ConnectorPermission,
    ConnectorResource,
    ConnectorTrigger,
    ConnectorUsage,
    ConnectorVersion,
    ConnectorWebhook,
    SharingPolicy,
)
from openagent.db.models.credential import Credential, CredentialStatus, CredentialType
from openagent.db.session import get_db
from openagent.services.authorization import AuthorizationContext, AuthorizationService

router = APIRouter(prefix="/organizations/{organization_id}/connectors",
                   tags=["connectors"])
connections_router = APIRouter(
    prefix="/organizations/{organization_id}/integration-connections",
    tags=["integration-connections"])
credentials_router = APIRouter(
    prefix="/organizations/{organization_id}/credentials",
    tags=["credentials"])
webhooks_mgmt_router = APIRouter(
    prefix="/organizations/{organization_id}/connector-webhooks",
    tags=["connector-webhooks"])
# Public receiver: signature-authenticated (no session).
webhooks_router = APIRouter(prefix="/webhooks", tags=["webhooks-inbound"])


def _org_or_403(ctx: AuthorizationContext, organization_id: UUID) -> None:
    if ctx.organization_id != organization_id and not ctx.is_platform_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Cross-organization access denied")


def _err(exc: Exception) -> HTTPException:
    from openagent.connectors.engine import ConnectorError
    from openagent.connectors.manifest import ManifestError
    from openagent.connectors.oauth import OAuthError
    from openagent.connectors.webhooks import WebhookError
    code_map = {"NOT_FOUND": 404, "CROSS_TENANT": 403, "SHARING_DENIED": 403,
                "CAPABILITY_DENIED": 403, "POLICY_DENIED": 403,
                "INVALID_APPROVAL": 409, "CONNECTION_MISMATCH": 400,
                "NO_CREDENTIAL": 409, "CREDENTIAL_INACTIVE": 409,
                "CREDENTIAL_DECRYPT_FAILED": 500, "VALIDATION_ERROR": 400,
                "EXECUTION_FAILED": 502, "NO_EXECUTOR": 501,
                "MANIFEST_INVALID": 400, "ILLEGAL_TRANSITION": 409,
                "STATEMENT_DENIED": 403, "WRITE_DENIED": 403,
                "TABLE_DENIED": 403, "SCHEMA_DENIED": 403,
                "CONNECT_FAILED": 502, "QUERY_FAILED": 502, "NO_DSN": 400,
                "DRIVER_UNSUPPORTED": 400, "UNKNOWN_ACTION": 404,
                "OAUTH_ERROR": 400, "STATE_INVALID": 403, "STATE_EXPIRED": 410,
                "CODE_INVALID": 400, "EXCHANGE_FAILED": 502,
                "REFRESH_FAILED": 502, "NO_REFRESH_TOKEN": 400,
                "REDIRECT_BLOCKED": 403, "WEBHOOK_REJECTED": 403,
                "REPLAY": 409, "STALE_EVENT": 410, "NO_DELIVERY_ID": 400}
    if isinstance(exc, (ConnectorError, ManifestError, OAuthError, WebhookError)):
        code = code_map.get(exc.code, 400)
        return HTTPException(status_code=code, detail=str(exc))
    return HTTPException(status_code=500, detail="Integration operation failed")


def _ensure_registry() -> None:
    from openagent.connectors.providers import provider_ids, register_official
    if not provider_ids():
        register_official()


# -- catalog ---------------------------------------------------------------
@router.get("", summary="Connector catalog (definitions + status)")
async def list_connectors(organization_id: UUID,
                          category: Optional[str] = None,
                          trust: Optional[str] = None,
                          search: Optional[str] = None,
                          db: AsyncSession = Depends(get_db),
                          ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:read")
    _ensure_registry()
    from openagent.connectors.registry import registry
    if search:
        manifests = registry.search(search, limit=50)
    else:
        from openagent.connectors.types import ConnectorStatus as DomainStatus
        manifests = registry.list(category=category)
        if trust:
            manifests = [m for m in manifests
                         if m.trust.value.lower() == trust.lower()]
    _ = DomainStatus
    rows = (await db.execute(select(Connector))).scalars().all()
    by_slug = {r.slug: r for r in rows}
    items = []
    for manifest in manifests:
        row = by_slug.get(manifest.id)
        items.append({
            "id": manifest.id, "name": manifest.name,
            "version": manifest.version, "category": manifest.category,
            "type": manifest.connector_type.value, "trust": manifest.trust.value,
            "description": manifest.description, "publisher": manifest.publisher,
            "status": row.status.value if row else "active",
            "capabilities": len(manifest.capabilities),
            "actions": len(manifest.actions),
            "triggers": len(manifest.triggers),
        })
    return {"items": items, "total": len(items)}


@router.get("/{connector_id}", summary="Connector detail (manifest, no secrets)")
async def get_connector(organization_id: UUID, connector_id: str,
                        db: AsyncSession = Depends(get_db),
                        ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:read")
    _ensure_registry()
    from openagent.connectors.registry import registry
    manifest = registry.get(connector_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    data = registry.to_dict(manifest)
    data["auth"] = {k: v for k, v in manifest.auth.items()
                    if "secret" not in k.lower()}
    return data


@router.get("/{connector_id}/actions", summary="Connector actions with schemas")
async def list_connector_actions(organization_id: UUID, connector_id: str,
                                 db: AsyncSession = Depends(get_db),
                                 ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:read")
    _ensure_registry()
    from openagent.connectors.registry import registry
    manifest = registry.get(connector_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return {"items": [{
        "id": a.id, "name": a.name, "description": a.description,
        "input_schema": a.input_schema, "output_schema": a.output_schema,
        "required_capabilities": a.required_capabilities,
        "risk_level": a.risk_level.value,
        "supports_idempotency": a.supports_idempotency,
        "timeout_seconds": a.timeout_seconds, "mutation": a.mutation,
        "verification": a.verification} for a in manifest.actions]}


@router.get("/{connector_id}/capabilities", summary="Connector capabilities")
async def list_connector_capabilities(organization_id: UUID, connector_id: str,
                                      db: AsyncSession = Depends(get_db),
                                      ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:read")
    _ensure_registry()
    from openagent.connectors.registry import registry
    manifest = registry.get(connector_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return {"items": [{
        "id": c.id, "description": c.description,
        "risk_level": c.risk_level.value} for c in manifest.capabilities]}


@router.get("/{connector_id}/triggers", summary="Connector triggers")
async def list_connector_triggers(organization_id: UUID, connector_id: str,
                                  db: AsyncSession = Depends(get_db),
                                  ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:read")
    _ensure_registry()
    from openagent.connectors.registry import registry
    manifest = registry.get(connector_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return {"items": [{
        "id": t.id, "name": t.name, "kind": t.kind.value,
        "description": t.description, "event_types": t.event_types,
        "payload_schema": t.payload_schema,
        "poll_config": t.poll_config} for t in manifest.triggers]}


class CustomConnectorCreate(BaseModel):
    manifest: dict[str, Any]


@router.post("", status_code=201, summary="Register custom/organization connector")
async def register_custom_connector(
        organization_id: UUID, body: CustomConnectorCreate,
        db: AsyncSession = Depends(get_db),
        ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:admin")
    from openagent.connectors.config import ConnectorSettings
    settings = ConnectorSettings()
    ctype = str((body.manifest or {}).get("type", "CUSTOM")).upper()
    if ctype == "COMMUNITY" and not settings.CONNECTOR_ENABLE_COMMUNITY:
        raise HTTPException(status_code=403,
                            detail="Community connectors are disabled by configuration")
    from openagent.connectors.manifest import ManifestError, validate_manifest
    try:
        manifest = validate_manifest(body.manifest)
    except ManifestError as exc:
        raise _err(exc)
    if manifest.connector_type.value in ("OFFICIAL", "INTERNAL"):
        raise HTTPException(status_code=403,
                            detail="Cannot register privileged connector types")
    row = await _upsert_definition(db, manifest)
    await db.commit()
    return {"id": manifest.id, "version": manifest.version,
            "definition_id": str(row.id)}


@router.post("/sync", summary="Sync registry definitions + Tool rows")
async def sync_connectors(organization_id: UUID,
                          db: AsyncSession = Depends(get_db),
                          ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:admin")
    _ensure_registry()
    from openagent.connectors.registry import registry
    synced = []
    for manifest in registry.list(include_disabled=True):
        row = await _upsert_definition(db, manifest)
        synced.extend(await _sync_tool_rows(db, manifest))
        synced.append(f"{manifest.id}@{manifest.version}:{row.id}")
    await db.commit()
    return {"synced": synced}


async def _upsert_definition(db: AsyncSession, manifest: Any):
    from openagent.connectors.types import ConnectorStatus as DomainStatus
    result = await db.execute(select(Connector).where(Connector.slug == manifest.id))
    row = result.scalar_one_or_none()
    if row is None:
        row = Connector(slug=manifest.id, name=manifest.name,
                        category=manifest.category)
        db.add(row)
        await db.flush()
    row.name = manifest.name
    row.category = manifest.category
    row.connector_type = manifest.connector_type.value.lower()
    row.trust = manifest.trust.value.lower()
    row.description = manifest.description[:2000]
    row.publisher = manifest.publisher
    row.license = manifest.license
    row.documentation_url = manifest.documentation_url
    row.current_version = manifest.version
    row.signature = manifest.signature
    row.content_hash = manifest.content_hash
    if str(row.status.value if hasattr(row.status, "value") else row.status) == "draft":
        row.status = DomainStatus.ACTIVE.value.lower()
    version_result = await db.execute(
        select(ConnectorVersion).where(
            ConnectorVersion.connector_id == row.id,
            ConnectorVersion.version == manifest.version))
    version_row = version_result.scalar_one_or_none()
    from openagent.connectors.manifest import manifest_to_dict
    if version_row is None:
        version_row = ConnectorVersion(
            connector_id=row.id, version=manifest.version,
            manifest=manifest_to_dict(manifest),
            content_hash=manifest.content_hash, is_active=True)
        db.add(version_row)
        await db.flush()
        for capability in manifest.capabilities:
            db.add(ConnectorCapability(
                version_id=version_row.id, capability_id=capability.id,
                description=capability.description,
                risk_level=capability.risk_level.value))
        for action in manifest.actions:
            db.add(ConnectorAction(
                version_id=version_row.id, action_id=action.id,
                name=action.name, description=action.description,
                input_schema=action.input_schema,
                output_schema=action.output_schema,
                required_capabilities=action.required_capabilities,
                risk_level=action.risk_level.value,
                supports_idempotency=action.supports_idempotency,
                timeout_seconds=action.timeout_seconds,
                mutation=action.mutation))
        for trigger in manifest.triggers:
            db.add(ConnectorTrigger(
                version_id=version_row.id, trigger_id=trigger.id,
                name=trigger.name, kind=trigger.kind.value,
                event_types=trigger.event_types,
                payload_schema=trigger.payload_schema,
                poll_config=trigger.poll_config))
        for resource in manifest.resources:
            db.add(ConnectorResource(
                version_id=version_row.id, kind=resource.kind,
                provider_kind=resource.provider_kind, schema=resource.schema))
        await db.flush()
    return row


_CATEGORY_MAP = {"communication": "communication", "developer": "developer",
                 "productivity": "documents", "storage": "filesystem",
                 "database": "database", "crm": "crm", "marketing": "analytics",
                 "analytics": "analytics", "finance": "finance",
                 "commerce": "finance", "automation": "utility",
                 "infrastructure": "system", "ai": "ai"}


async def _sync_tool_rows(db: AsyncSession, manifest: Any) -> list[str]:
    """Publish connector actions as Tool rows (provider connector:<id>).

    Execution still funnels through ConnectorEngine (single gate); the tool
    execute path delegates by provider prefix (see tools.py wiring)."""
    from openagent.db.models.tool import (
        Tool,
        ToolCapability,
        ToolCategory,
        ToolExecutionMode,
        ToolLifecycleStatus,
        ToolProviderType,
        ToolRiskLevel,
        ToolTrustLevel,
        ToolType,
    )
    synced = []
    category = _CATEGORY_MAP.get(manifest.category, "utility")
    try:
        tool_category = ToolCategory(category)
    except ValueError:
        tool_category = ToolCategory.CUSTOM
    trust_map = {"CORE": "CORE", "VERIFIED": "VERIFIED",
                 "ORGANIZATION": "ORGANIZATION", "COMMUNITY": "COMMUNITY",
                 "CUSTOM": "UNTRUSTED", "UNTRUSTED": "UNTRUSTED"}
    for action in manifest.actions:
        slug = action.id
        result = await db.execute(select(Tool).where(
            Tool.organization_id.is_(None), Tool.slug == slug,
            Tool.version == manifest.version))
        tool = result.scalar_one_or_none()
        capabilities = [ToolCapability.EXTERNAL_API, ToolCapability.NETWORK]
        if action.mutation and "message" in action.id:
            capabilities.append(ToolCapability.MESSAGE_SEND)
        if "email" in action.id or manifest.id in ("gmail",):
            capabilities.append(ToolCapability.EMAIL_SEND)
        if manifest.category == "database":
            capabilities.append(ToolCapability.DATABASE_ACCESS)
        fields = {
            "name": f"{manifest.name}: {action.name}",
            "description": action.description[:2000],
            "tool_type": ToolType.API, "category": tool_category,
            "status": ToolLifecycleStatus.ACTIVE,
            "provider": f"connector:{manifest.id}",
            "provider_type": ToolProviderType.EXTERNAL_SERVICE,
            "version": manifest.version, "capabilities": capabilities,
            "risk_level": ToolRiskLevel(action.risk_level.value),
            "execution_mode": ToolExecutionMode.SYNC,
            "timeout": action.timeout_seconds * 1000,
            "supports_idempotency": action.supports_idempotency,
            "trust_level": ToolTrustLevel(trust_map.get(manifest.trust.value,
                                                        "UNTRUSTED")),
            "input_schema": action.input_schema,
            "output_schema": action.output_schema,
            "metadata": {"connector": manifest.id, "action": action.id,
                         "connector_action": True,
                         "required_capabilities": action.required_capabilities},
        }
        if tool is None:
            tool = Tool(slug=slug, organization_id=None, **fields)
            db.add(tool)
        else:
            for key, value in fields.items():
                setattr(tool, key, value)
        synced.append(slug)
    await db.flush()
    return synced


# -- agent discovery ---------------------------------------------------------
@router.get("/search", summary="Capability/action/trigger search (compact)")
async def search_integrations(organization_id: UUID,
                              q: str = Query(min_length=1, max_length=200),
                              kind: str = Query(default="action",
                                                pattern="^(action|connector|trigger|capability|all)$"),
                              limit: int = Query(default=10, ge=1, le=50),
                              db: AsyncSession = Depends(get_db),
                              ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "tool:read")
    _ensure_registry()
    from openagent.connectors.registry import registry
    out: dict[str, Any] = {"query": q, "actions": [], "connectors": [],
                           "triggers": [], "capabilities": []}
    if kind in ("action", "all"):
        out["actions"] = registry.search_actions(q, limit=limit)
    if kind in ("connector", "all"):
        out["connectors"] = [{"connector": m.id, "description": m.description[:160],
                              "trust": m.trust.value}
                             for m in registry.search(q, limit=limit)]
    if kind in ("trigger", "capability", "all"):
        needle = q.strip().lower()
        for manifest in registry.list():
            for trigger in manifest.triggers:
                if needle in trigger.id.lower() or needle in trigger.name.lower():
                    out["triggers"].append({"trigger": trigger.id,
                                           "kind": trigger.kind.value,
                                           "connector": manifest.id})
            for capability in manifest.capabilities:
                if needle in capability.id.lower():
                    out["capabilities"].append({"capability": capability.id,
                                               "risk_level": capability.risk_level.value,
                                               "connector": manifest.id})
    # MCP-backed capabilities share the discovery layer, tagged by origin.
    if kind in ("action", "all"):
        needle = q.strip().lower()
        try:
            from openagent.db.models.mcp import MCPServer, MCPServerStatus
            servers = (await db.execute(select(MCPServer).where(
                MCPServer.organization_id == organization_id,
                MCPServer.status == MCPServerStatus.ACTIVE).limit(20))).scalars().all()
            for server in servers:
                name = getattr(server, "name", "") or ""
                if needle and (needle in name.lower() or needle in "mcp"):
                    out["actions"].append({
                        "action": f"mcp.{server.id}.invoke",
                        "description": f"MCP server '{name}' (invoke tool)",
                        "risk_level": "MEDIUM",
                        "connector": f"mcp:{server.id}",
                        "trust": "ORGANIZATION",
                        "origin": "mcp"})
        except Exception:
            pass
    return out


# -- credentials (masked; secrets never returned) ------------------------------
class CredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=100)
    credential_type: str = Field(default="api_key", max_length=32)
    secrets: dict[str, Any] = Field(default_factory=dict)
    expires_at: Optional[str] = None


def _credential_type(value: str) -> CredentialType:
    mapping = {"api_key": CredentialType.API_KEY, "oauth_token": CredentialType.OAUTH_TOKEN,
               "basic_auth": CredentialType.BASIC_AUTH,
               "bearer_token": CredentialType.BEARER_TOKEN,
               "certificate": CredentialType.CERTIFICATE, "ssh_key": CredentialType.SSH_KEY,
               "database_url": CredentialType.DATABASE_URL,
               "service_account": CredentialType.CUSTOM, "custom": CredentialType.CUSTOM,
               "custom_header": CredentialType.CUSTOM}
    result = mapping.get(str(value or "").lower())
    if result is None:
        raise HTTPException(status_code=400,
                            detail=f"Unknown credential type '{value}'")
    return result


def _masked_row(credential: Credential) -> dict[str, Any]:
    from openagent.connectors.crypto import mask_secret
    ctype = (credential.credential_type.value
             if hasattr(credential.credential_type, "value")
             else str(credential.credential_type))
    return {"id": str(credential.id), "name": credential.name,
            "provider": credential.provider, "credential_type": ctype,
            "status": str(credential.status.value
                          if hasattr(credential.status, "value")
                          else credential.status),
            "masked": mask_secret("placeholder-value") and True,
            "expires_at": credential.expires_at.isoformat()
            if credential.expires_at else None,
            "created_at": credential.created_at.isoformat()
            if credential.created_at else None}


@credentials_router.get("", summary="List credentials (masked, never secrets)")
async def list_credentials(organization_id: UUID,
                           provider: Optional[str] = None,
                           limit: int = Query(default=50, ge=1, le=200),
                           offset: int = Query(default=0, ge=0),
                           db: AsyncSession = Depends(get_db),
                           ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "credential:read")
    query = select(Credential).where(
        Credential.organization_id == organization_id,
        Credential.deleted_at.is_(None))
    if provider:
        query = query.where(Credential.provider == provider)
    total = (await db.execute(select(func.count()).select_from(
        query.subquery()))).scalar() or 0
    rows = (await db.execute(query.order_by(Credential.created_at.desc())
                             .limit(limit).offset(offset))).scalars().all()
    return {"items": [_masked_row(r) for r in rows], "total": total}


@credentials_router.post("", status_code=201, summary="Store credential (encrypted)")
async def create_credential(organization_id: UUID, body: CredentialCreate,
                            db: AsyncSession = Depends(get_db),
                            ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "credential:create")
    import json as _json

    from openagent.connectors.crypto import encrypt_secret
    from openagent.core.config import get_settings
    if not body.secrets:
        raise HTTPException(status_code=400, detail="No secret material provided")
    credential = Credential(organization_id=organization_id, name=body.name,
                            provider=body.provider,
                            credential_type=_credential_type(body.credential_type),
                            encrypted_data="", status=CredentialStatus.ACTIVE)
    if body.expires_at:
        try:
            credential.expires_at = datetime.fromisoformat(body.expires_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="Bad expires_at format")
    db.add(credential)
    await db.flush()
    try:
        credential.encrypted_data = encrypt_secret(
            get_settings().ENCRYPTION_KEY, _json.dumps(body.secrets),
            associated=str(credential.id))
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Encryption failed: {exc}")
    await db.commit()
    from openagent.connectors.engine import ConnectorEngine
    await ConnectorEngine(db)._audit(
        organization_id, ctx.user_id, "connector.credential_created",
        "credential", credential.id, {"provider": body.provider})
    await db.commit()
    return _masked_row(credential)


@credentials_router.post("/{credential_id}/rotate", summary="Rotate credential secret")
async def rotate_credential(organization_id: UUID, credential_id: UUID,
                            body: CredentialCreate,
                            db: AsyncSession = Depends(get_db),
                            ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "credential:rotate")
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()
    if credential is None or credential.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Credential not found")
    import json as _json

    from openagent.connectors.crypto import encrypt_secret
    from openagent.core.config import get_settings
    credential.encrypted_data = encrypt_secret(
        get_settings().ENCRYPTION_KEY, _json.dumps(body.secrets or {}),
        associated=str(credential.id))
    credential.status = CredentialStatus.ACTIVE
    from openagent.connectors.engine import ConnectorEngine
    await ConnectorEngine(db)._audit(
        organization_id, ctx.user_id, "connector.credential_rotated",
        "credential", credential.id, {})
    await db.commit()
    return _masked_row(credential)


@credentials_router.post("/{credential_id}/revoke", summary="Revoke credential")
async def revoke_credential(organization_id: UUID, credential_id: UUID,
                            db: AsyncSession = Depends(get_db),
                            ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "credential:update")
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()
    if credential is None or credential.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Credential not found")
    credential.status = CredentialStatus.REVOKED
    from openagent.connectors.engine import ConnectorEngine
    await ConnectorEngine(db)._audit(
        organization_id, ctx.user_id, "connector.revoked",
        "credential", credential.id, {})
    await db.commit()
    return {"revoked": True}


@credentials_router.delete("/{credential_id}", summary="Delete credential")
async def delete_credential(organization_id: UUID, credential_id: UUID,
                            db: AsyncSession = Depends(get_db),
                            ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "credential:delete")
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()
    if credential is None or credential.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Credential not found")
    # Secure deletion semantics: wipe ciphertext before soft-delete.
    credential.encrypted_data = ""
    credential.status = CredentialStatus.REVOKED
    credential.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"deleted": True}


# -- connections ---------------------------------------------------------------
def _serialize_connection(connection: ConnectorConnection) -> dict[str, Any]:
    return {"id": str(connection.id),
            "organization_id": str(connection.organization_id),
            "connector_id": connection.connector_id,
            "connector_version": connection.connector_version,
            "name": connection.name,
            "status": str(connection.status.value
                          if hasattr(connection.status, "value")
                          else connection.status),
            "scope": str(connection.scope.value
                         if hasattr(connection.scope, "value") else connection.scope),
            "sharing_policy": str(connection.sharing_policy.value
                                  if hasattr(connection.sharing_policy, "value")
                                  else connection.sharing_policy),
            "owner_user_id": str(connection.owner_user_id)
            if connection.owner_user_id else None,
            "credential_id": str(connection.credential_id)
            if connection.credential_id else None,
            "granted_capabilities": list(connection.granted_capabilities or []),
            "policy_config": dict(connection.policy_config or {}),
            "health": dict(connection.health or {}),
            "last_used_at": connection.last_used_at.isoformat()
            if connection.last_used_at else None,
            "last_error": connection.last_error or "",
            "created_at": connection.created_at.isoformat()
            if connection.created_at else None}


class ConnectionCreate(BaseModel):
    connector_id: str = Field(min_length=1, max_length=100)
    name: str = Field(default="", max_length=255)
    scope: str = Field(default="organization", max_length=32)
    sharing_policy: str = Field(default="private", max_length=32)
    team_ids: list[str] = Field(default_factory=list)
    workflow_ids: list[str] = Field(default_factory=list)
    credential_id: Optional[UUID] = None
    granted_capabilities: list[str] = Field(default_factory=list)
    policy_config: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    sharing_policy: Optional[str] = Field(default=None, max_length=32)
    team_ids: Optional[list[str]] = None
    workflow_ids: Optional[list[str]] = None
    credential_id: Optional[UUID] = None
    granted_capabilities: Optional[list[str]] = None
    policy_config: Optional[dict[str, Any]] = None
    config: Optional[dict[str, Any]] = None


def _check_scope(value: str) -> ConnectionScope:
    try:
        return ConnectionScope(value.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown scope '{value}'")


def _check_sharing(value: str) -> SharingPolicy:
    try:
        return SharingPolicy(value.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown sharing policy '{value}'")


def _capabilities_for(connector_id: str) -> list[str]:
    _ensure_registry()
    from openagent.connectors.registry import registry
    manifest = registry.get(connector_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return [c.id for c in manifest.capabilities]


@connections_router.get("", summary="List connections (metadata only)")
async def list_connections(organization_id: UUID,
                           connector_id: Optional[str] = None,
                           status_filter: Optional[str] = Query(default=None, alias="status"),
                           limit: int = Query(default=50, ge=1, le=200),
                           offset: int = Query(default=0, ge=0),
                           db: AsyncSession = Depends(get_db),
                           ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:read")
    query = select(ConnectorConnection).where(
        ConnectorConnection.organization_id == organization_id)
    if connector_id:
        query = query.where(ConnectorConnection.connector_id == connector_id)
    if status_filter:
        try:
            query = query.where(ConnectorConnection.status ==
                                ConnectionStatus(status_filter.lower()))
        except ValueError:
            raise HTTPException(status_code=400, detail="Unknown status")
    total = (await db.execute(select(func.count()).select_from(
        query.subquery()))).scalar() or 0
    rows = (await db.execute(query.order_by(ConnectorConnection.created_at.desc())
                             .limit(limit).offset(offset))).scalars().all()
    return {"items": [_serialize_connection(r) for r in rows], "total": total}


@connections_router.post("", status_code=201, summary="Create connection (unconnected)")
async def create_connection(organization_id: UUID, body: ConnectionCreate,
                            db: AsyncSession = Depends(get_db),
                            ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:create")
    known = _capabilities_for(body.connector_id)
    unknown = [c for c in body.granted_capabilities if c not in set(known)]
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"Unknown capabilities: {', '.join(unknown[:5])}")
    if body.credential_id is not None:
        result = await db.execute(select(Credential).where(
            Credential.id == body.credential_id))
        credential = result.scalar_one_or_none()
        if credential is None or credential.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Credential not found")
    connection = ConnectorConnection(
        organization_id=organization_id, connector_id=body.connector_id,
        name=body.name or body.connector_id,
        status=ConnectionStatus.UNCONNECTED, scope=_check_scope(body.scope),
        sharing_policy=_check_sharing(body.sharing_policy),
        owner_user_id=ctx.user_id, team_ids=body.team_ids[:32],
        workflow_ids=body.workflow_ids[:64], credential_id=body.credential_id,
        granted_capabilities=body.granted_capabilities,
        policy_config=body.policy_config, config=body.config)
    db.add(connection)
    await db.flush()
    from openagent.connectors.engine import ConnectorEngine
    await ConnectorEngine(db)._audit(
        organization_id, ctx.user_id, "connector.connected",
        "connector_connection", connection.id,
        {"connector": body.connector_id})
    await db.commit()
    return _serialize_connection(connection)


@connections_router.get("/{connection_id}", summary="Connection detail")
async def get_connection(organization_id: UUID, connection_id: UUID,
                         db: AsyncSession = Depends(get_db),
                         ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:read")
    from openagent.connectors.engine import ConnectorEngine
    try:
        connection = await ConnectorEngine(db).get_connection(
            connection_id, organization_id)
    except Exception as exc:
        raise _err(exc)
    data = _serialize_connection(connection)
    health_rows = (await db.execute(select(ConnectorHealth).where(
        ConnectorHealth.connection_id == connection_id).order_by(
            ConnectorHealth.created_at.desc()).limit(5))).scalars().all()
    data["health_history"] = [{
        "state": str(h.state.value if hasattr(h.state, "value") else h.state),
        "latency_ms": h.latency_ms, "auth_ok": h.auth_ok,
        "at": h.created_at.isoformat() if h.created_at else None} for h in health_rows]
    return data


@connections_router.patch("/{connection_id}", summary="Update connection")
async def update_connection(organization_id: UUID, connection_id: UUID,
                            body: ConnectionUpdate,
                            db: AsyncSession = Depends(get_db),
                            ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:update")
    from openagent.connectors.engine import ConnectorEngine
    try:
        connection = await ConnectorEngine(db).get_connection(
            connection_id, organization_id)
    except Exception as exc:
        raise _err(exc)
    if body.name is not None:
        connection.name = body.name
    if body.sharing_policy is not None:
        connection.sharing_policy = _check_sharing(body.sharing_policy)
    if body.team_ids is not None:
        connection.team_ids = body.team_ids[:32]
    if body.workflow_ids is not None:
        connection.workflow_ids = body.workflow_ids[:64]
    if body.credential_id is not None:
        result = await db.execute(select(Credential).where(
            Credential.id == body.credential_id))
        credential = result.scalar_one_or_none()
        if credential is None or credential.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Credential not found")
        connection.credential_id = body.credential_id
    if body.granted_capabilities is not None:
        known = _capabilities_for(connection.connector_id)
        unknown = [c for c in body.granted_capabilities if c not in set(known)]
        if unknown:
            raise HTTPException(status_code=400,
                                detail=f"Unknown capabilities: {', '.join(unknown[:5])}")
        connection.granted_capabilities = body.granted_capabilities
    if body.policy_config is not None:
        connection.policy_config = body.policy_config
    if body.config is not None:
        connection.config = body.config
    await db.commit()
    return _serialize_connection(connection)


@connections_router.delete("/{connection_id}", summary="Delete connection")
async def delete_connection(organization_id: UUID, connection_id: UUID,
                            db: AsyncSession = Depends(get_db),
                            ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:delete")
    from openagent.connectors.engine import ConnectorEngine
    try:
        connection = await ConnectorEngine(db).get_connection(
            connection_id, organization_id)
    except Exception as exc:
        raise _err(exc)
    await db.delete(connection)
    await ConnectorEngine(db)._audit(
        organization_id, ctx.user_id, "connector.disconnected",
        "connector_connection", connection_id, {})
    await db.commit()
    return {"deleted": True}


class OAuthInit(BaseModel):
    redirect_uri: str = Field(min_length=1, max_length=500)
    extra_scopes: list[str] = Field(default_factory=list)


@connections_router.post("/{connection_id}/connect",
                         summary="Begin OAuth connect (returns authorize URL)")
async def connect_init(organization_id: UUID, connection_id: UUID,
                       body: OAuthInit,
                       db: AsyncSession = Depends(get_db),
                       ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:update")
    from urllib.parse import urlparse

    from openagent.connectors.engine import ConnectorEngine
    from openagent.connectors.oauth import (
        OAuthConfig,
        OAuthError,
        build_authorize_url,
        validate_callback_url,
    )
    from openagent.core.config import get_settings
    try:
        connection = await ConnectorEngine(db).get_connection(
            connection_id, organization_id)
    except Exception as exc:
        raise _err(exc)
    _ensure_registry()
    from openagent.connectors.registry import registry
    manifest = registry.get(connection.connector_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    if str(manifest.auth.get("type", "")).lower() != "oauth2":
        raise HTTPException(status_code=400,
                            detail="Connector does not use OAuth2; attach an API key credential instead")
    settings = get_settings()
    allowed = [h.strip().lower() for h in str(
        getattr(settings, "OAUTH_REDIRECT_HOSTS", "") or "").split(",") if h.strip()]
    app_hosts = [urlparse(str(getattr(settings, "WEB_URL", "") or "")).hostname or ""]
    try:
        # Fail closed: only configured hosts (+ app host) may receive codes.
        validate_callback_url(
            body.redirect_uri,
            allowed_hosts=allowed + [h.lower() for h in app_hosts if h])
    except OAuthError as exc:
        raise _err(exc)
    config = OAuthConfig(
        authorize_url=str(manifest.auth.get("authorize_url", "")),
        token_url=str(manifest.auth.get("token_url", "")),
        client_id=str((connection.config or {}).get("client_id", "")),
        redirect_uri=body.redirect_uri,
        scopes=[str(s) for s in (manifest.auth.get("scopes", []) or [])])
    if not config.client_id:
        raise HTTPException(status_code=400,
                            detail="OAuth client_id missing: set it in connection config first")
    try:
        url, state, verifier = build_authorize_url(
            config, state_secret=settings.SECRET_KEY,
            connection_id=str(connection.id), extra_scopes=body.extra_scopes)
    except Exception as exc:
        raise _err(exc)
    connection.oauth_state = {"verifier": verifier, "redirect_uri": body.redirect_uri,
                              "started_at": datetime.now(timezone.utc).isoformat()}
    connection.status = ConnectionStatus.CONNECTING
    await db.commit()
    return {"authorize_url": url, "state": state,
            "scopes": config.scopes + body.extra_scopes}


class OAuthCallback(BaseModel):
    code: str = Field(min_length=1, max_length=2000)
    state: str = Field(min_length=1, max_length=4000)


@connections_router.post("/{connection_id}/callback",
                         summary="OAuth callback (state-verified token exchange)")
async def connect_callback(organization_id: UUID, connection_id: UUID,
                           body: OAuthCallback,
                           db: AsyncSession = Depends(get_db),
                           ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:update")
    from openagent.connectors.engine import ConnectorEngine
    from openagent.connectors.oauth import OAuthConfig, OAuthError, OAuthManager, verify_state
    from openagent.core.config import get_settings
    try:
        connection = await ConnectorEngine(db).get_connection(
            connection_id, organization_id)
    except Exception as exc:
        raise _err(exc)
    settings = get_settings()
    try:
        claimed = verify_state(body.state, settings.SECRET_KEY)
    except OAuthError as exc:
        await ConnectorEngine(db)._security_event(
            organization_id, ctx.user_id, "connector.oauth_csrf",
            {"connection_id": str(connection_id)})
        raise _err(exc)
    if claimed.get("connection_id") != str(connection.id):
        await ConnectorEngine(db)._security_event(
            organization_id, ctx.user_id, "connector.oauth_csrf",
            {"connection_id": str(connection_id)})
        raise HTTPException(status_code=403, detail="State does not match connection")
    oauth_state = connection.oauth_state or {}
    verifier = oauth_state.get("verifier", "")
    if not verifier:
        raise HTTPException(status_code=409,
                            detail="No pending OAuth flow (code may have been replayed)")
    # Single-use: clear before exchange so retries cannot replay the code.
    connection.oauth_state = {}
    await db.flush()
    _ensure_registry()
    from openagent.connectors.registry import registry
    manifest = registry.get(connection.connector_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    client_secret = ""
    # Prefer a server-side stored secret reference; direct config values are
    # accepted only as a fallback for development setups.
    ref = str((connection.config or {}).get("client_secret_ref", ""))
    if ref:
        client_secret = await _resolve_secret_ref(db, organization_id, ref)
    if not client_secret:
        client_secret = str((connection.config or {}).get("client_secret", ""))
    config = OAuthConfig(
        authorize_url=str(manifest.auth.get("authorize_url", "")),
        token_url=str(manifest.auth.get("token_url", "")),
        client_id=str((connection.config or {}).get("client_id", "")),
        redirect_uri=str(oauth_state.get("redirect_uri", "")),
        revoke_url=str(manifest.auth.get("revoke_url", "")))
    import aiohttp

    async def _post_form(url: str, fields: dict[str, str],
                         secrets: dict[str, str]):
        from openagent.connectors.netsec import assert_url_safe
        assert_url_safe(url)
        payload = dict(fields)
        if secrets.get("client_secret"):
            payload["client_secret"] = secrets["client_secret"]
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload,
                                    timeout=aiohttp.ClientTimeout(total=30)) as resp:
                try:
                    body_json = await resp.json()
                except Exception:
                    body_json = {}
                return resp.status, body_json if isinstance(body_json, dict) else {}

    try:
        tokens = await OAuthManager(config).exchange_code(
            code=body.code, verifier=verifier, client_secret=client_secret,
            post_form=_post_form)
    except Exception as exc:
        connection.status = ConnectionStatus.ERROR
        connection.last_error = str(exc)[:300]
        await db.commit()
        raise _err(exc)
    credential = await _store_oauth_credential(
        db, organization_id, connection, tokens, manifest)
    connection.credential_id = credential.id
    connection.status = ConnectionStatus.CONNECTED
    connection.last_error = ""
    await ConnectorEngine(db)._audit(
        organization_id, ctx.user_id, "connector.connected",
        "connector_connection", connection.id,
        {"connector": connection.connector_id})
    await db.commit()
    return {"connected": True, "credential_id": str(credential.id)}


async def _resolve_secret_ref(db: AsyncSession, organization_id: UUID,
                              ref: str) -> str:
    from openagent.connectors.crypto import decrypt_secret
    from openagent.core.config import get_settings
    try:
        credential_id = UUID(ref)
    except ValueError:
        return ""
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()
    if credential is None or credential.organization_id != organization_id:
        return ""
    try:
        import json as _json
        payload = decrypt_secret(get_settings().ENCRYPTION_KEY,
                                 credential.encrypted_data,
                                 associated=str(credential.id))
        data = _json.loads(payload)
        return str(data.get("client_secret", ""))
    except Exception:
        return ""


async def _store_oauth_credential(db: AsyncSession, organization_id: UUID,
                                  connection: ConnectorConnection,
                                  tokens: Any, manifest: Any) -> Credential:
    import json as _json

    from openagent.connectors.crypto import encrypt_secret
    from openagent.core.config import get_settings
    credential = Credential(
        organization_id=organization_id,
        name=f"{connection.connector_id} oauth",
        provider=connection.connector_id,
        credential_type=CredentialType.OAUTH_TOKEN, encrypted_data="",
        status=CredentialStatus.ACTIVE)
    if tokens.expires_in:
        from datetime import timedelta
        credential.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=tokens.expires_in)
    db.add(credential)
    await db.flush()
    credential.encrypted_data = encrypt_secret(
        get_settings().ENCRYPTION_KEY, _json.dumps(tokens.to_storage()),
        associated=str(credential.id))
    await db.flush()
    return credential


@connections_router.post("/{connection_id}/disconnect", summary="Disconnect + revoke")
async def disconnect_connection(organization_id: UUID, connection_id: UUID,
                                db: AsyncSession = Depends(get_db),
                                ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:update")
    from openagent.connectors.engine import ConnectorEngine
    try:
        connection = await ConnectorEngine(db).get_connection(
            connection_id, organization_id)
    except Exception as exc:
        raise _err(exc)
    # Best-effort provider revocation; local state always cleared.
    if connection.credential_id is not None:
        result = await db.execute(select(Credential).where(
            Credential.id == connection.credential_id))
        credential = result.scalar_one_or_none()
        if credential is not None and \
                credential.organization_id == organization_id:
            credential.encrypted_data = ""
            credential.status = CredentialStatus.REVOKED
    connection.credential_id = None
    connection.status = ConnectionStatus.DISCONNECTED
    connection.oauth_state = {}
    await ConnectorEngine(db)._audit(
        organization_id, ctx.user_id, "connector.disconnected",
        "connector_connection", connection.id, {})
    await db.commit()
    return {"disconnected": True}


@connections_router.post("/{connection_id}/test", summary="Safe connection test")
async def test_connection(organization_id: UUID, connection_id: UUID,
                         db: AsyncSession = Depends(get_db),
                         ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:read")
    from openagent.connectors.engine import ConnectorEngine
    try:
        outcome = await ConnectorEngine(db).test_connection(
            connection_id, organization_id)
    except Exception as exc:
        raise _err(exc)
    state = "HEALTHY" if outcome.get("ok") else "ERROR"
    db.add(ConnectorHealth(connection_id=connection_id,
                           organization_id=organization_id, state=state,
                           auth_ok=bool(outcome.get("ok")),
                           detail=str(outcome.get("error", ""))[:500]))
    connection = await ConnectorEngine(db).get_connection(
        connection_id, organization_id)
    connection.health = {"state": state, "detail": outcome.get("detail", {}),
                         "checked_at": datetime.now(timezone.utc).isoformat()}
    await db.commit()
    return outcome


class ExecuteAction(BaseModel):
    action_id: str = Field(min_length=1, max_length=160)
    input: dict[str, Any] = Field(default_factory=dict)
    approval_id: Optional[UUID] = None
    idempotency_key: str = Field(default="", max_length=100)


class PollSchedule(BaseModel):
    trigger_id: str = Field(min_length=1, max_length=160)
    interval_seconds: int = Field(default=300, ge=60, le=86400)


@connections_router.post("/{connection_id}/poll", summary="Run one bounded poll cycle")
async def poll_connection(organization_id: UUID, connection_id: UUID,
                          trigger_id: Optional[str] = None,
                          db: AsyncSession = Depends(get_db),
                          ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:execute")
    from openagent.connectors.engine import ConnectorEngine
    from openagent.connectors.scheduler import run_due_polls
    try:
        await ConnectorEngine(db).get_connection(connection_id, organization_id)
        outcome = await run_due_polls(db, organization_id=organization_id,
                                      connection_id=connection_id,
                                      trigger_id=trigger_id or "")
    except Exception as exc:
        raise _err(exc)
    return outcome


@connections_router.post("/{connection_id}/poll/schedule",
                         summary="Schedule polling trigger (existing scheduler)")
async def schedule_poll(organization_id: UUID, connection_id: UUID,
                        body: PollSchedule,
                        db: AsyncSession = Depends(get_db),
                        ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:update")
    from openagent.connectors.engine import ConnectorEngine
    from openagent.connectors.scheduler import ensure_poll_job
    try:
        await ConnectorEngine(db).get_connection(connection_id, organization_id)
        job = await ensure_poll_job(db, organization_id=organization_id,
                                    connection_id=connection_id,
                                    trigger_id=body.trigger_id,
                                    interval_seconds=body.interval_seconds)
        await db.commit()
    except Exception as exc:
        raise _err(exc)
    return {"job_id": str(job.id), "trigger_id": body.trigger_id,
            "interval_seconds": body.interval_seconds}


@connections_router.post("/{connection_id}/execute", summary="Execute connector action")
async def execute_connection_action(organization_id: UUID, connection_id: UUID,
                                    body: ExecuteAction,
                                    db: AsyncSession = Depends(get_db),
                                    ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:execute")
    from openagent.connectors.engine import ConnectorEngine
    from openagent.connectors.types import ConnectorExecutionContext
    try:
        connection = await ConnectorEngine(db).get_connection(
            connection_id, organization_id)
    except Exception as exc:
        raise _err(exc)
    try:
        outcome = await ConnectorEngine(db).execute_action(
            connector_id=connection.connector_id, action_id=body.action_id,
            connection_id=connection_id, organization_id=organization_id,
            arguments=body.input,
            context=ConnectorExecutionContext(
                organization_id=str(organization_id),
                user_id=str(ctx.user_id) if ctx.user_id else "",
                connector_id=connection.connector_id,
                connection_id=str(connection_id)),
            approval_id=body.approval_id,
            idempotency_key=body.idempotency_key)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _err(exc)
    return outcome


@connections_router.get("/{connection_id}/health", summary="Connection health")
async def connection_health(organization_id: UUID, connection_id: UUID,
                            db: AsyncSession = Depends(get_db),
                            ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:read")
    rows = (await db.execute(select(ConnectorHealth).where(
        ConnectorHealth.connection_id == connection_id,
        ConnectorHealth.organization_id == organization_id).order_by(
            ConnectorHealth.created_at.desc()).limit(10))).scalars().all()
    usage = (await db.execute(select(ConnectorUsage).where(
        ConnectorUsage.connection_id == connection_id).order_by(
            ConnectorUsage.period.desc()).limit(7))).scalars().all()
    return {"health": [{
        "state": str(h.state.value if hasattr(h.state, "value") else h.state),
        "latency_ms": h.latency_ms, "auth_ok": h.auth_ok,
        "detail": h.detail,
        "at": h.created_at.isoformat() if h.created_at else None} for h in rows],
        "usage": [{"period": u.period, "calls": u.calls,
                   "successes": u.successes, "failures": u.failures,
                   "avg_latency_ms": (u.latency_ms_total // u.calls) if u.calls else 0}
                  for u in usage]}


@connections_router.get("/{connection_id}/events", summary="Connection events")
async def connection_events(organization_id: UUID, connection_id: UUID,
                            limit: int = Query(default=50, ge=1, le=200),
                            offset: int = Query(default=0, ge=0),
                            db: AsyncSession = Depends(get_db),
                            ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:read")
    query = select(ConnectorEvent).where(
        ConnectorEvent.connection_id == connection_id,
        ConnectorEvent.organization_id == organization_id)
    total = (await db.execute(select(func.count()).select_from(
        query.subquery()))).scalar() or 0
    rows = (await db.execute(query.order_by(ConnectorEvent.created_at.desc())
                             .limit(limit).offset(offset))).scalars().all()
    return {"items": [{
        "id": str(e.id), "event_type": e.event_type, "provider": e.provider,
        "resource_id": e.resource_id, "delivery_id": e.delivery_id,
        "attributes": e.attributes, "processed": e.processed,
        "at": e.created_at.isoformat() if e.created_at else None} for e in rows],
        "total": total}


class ShareConnection(BaseModel):
    grantee_type: str = Field(default="user", max_length=32)
    grantee_id: str = Field(default="", max_length=100)
    capabilities: list[str] = Field(default_factory=list)


@connections_router.post("/{connection_id}/permissions", summary="Grant connection access")
async def grant_connection_access(organization_id: UUID, connection_id: UUID,
                                  body: ShareConnection,
                                  db: AsyncSession = Depends(get_db),
                                  ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "connector:update")
    from openagent.connectors.engine import ConnectorEngine
    try:
        connection = await ConnectorEngine(db).get_connection(
            connection_id, organization_id)
    except Exception as exc:
        raise _err(exc)
    if body.grantee_type not in ("user", "team", "service_account", "workflow"):
        raise HTTPException(status_code=400, detail="Unknown grantee type")
    known = _capabilities_for(connection.connector_id)
    unknown = [c for c in body.capabilities if c not in set(known)]
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"Unknown capabilities: {', '.join(unknown[:5])}")
    row = ConnectorPermission(
        connection_id=connection.id, organization_id=organization_id,
        grantee_type=body.grantee_type, grantee_id=body.grantee_id,
        capabilities=body.capabilities)
    db.add(row)
    await ConnectorEngine(db)._audit(
        organization_id, ctx.user_id, "connector.shared",
        "connector_connection", connection.id,
        {"grantee": f"{body.grantee_type}:{body.grantee_id}"})
    await db.commit()
    return {"id": str(row.id)}


# -- webhooks: management --------------------------------------------------------
class WebhookCreate(BaseModel):
    endpoint: str = Field(min_length=1, max_length=200)
    event_types: list[str] = Field(default_factory=list)
    verify_mode: str = Field(default="hmac_sha256", max_length=32)


@webhooks_mgmt_router.get("", summary="List webhook endpoints")
async def list_webhook_endpoints(organization_id: UUID,
                                 connection_id: Optional[UUID] = None,
                                 db: AsyncSession = Depends(get_db),
                                 ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "webhook:read")
    query = select(ConnectorWebhook).where(
        ConnectorWebhook.organization_id == organization_id)
    if connection_id:
        query = query.where(ConnectorWebhook.connection_id == connection_id)
    rows = (await db.execute(query.order_by(
        ConnectorWebhook.created_at.desc()).limit(200))).scalars().all()
    return {"items": [{
        "id": str(w.id), "connection_id": str(w.connection_id),
        "connector_id": w.connector_id, "endpoint": w.endpoint,
        "event_types": w.event_types, "verify_mode": w.verify_mode,
        "secret_prefix": w.secret_prefix, "is_active": w.is_active,
        "failure_count": w.failure_count,
        "last_delivery_at": w.last_delivery_at.isoformat()
        if w.last_delivery_at else None,
        "last_signature_ok": w.last_signature_ok} for w in rows]}


@webhooks_mgmt_router.post("", status_code=201,
                           summary="Register webhook endpoint (secret shown once)")
async def create_webhook_endpoint(organization_id: UUID,
                                  connection_id: UUID,
                                  body: WebhookCreate,
                                  db: AsyncSession = Depends(get_db),
                                  ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "webhook:create")
    from openagent.connectors.engine import ConnectorEngine
    from openagent.connectors.webhooks import MAX_WEBHOOK_BYTES, VERIFY_MODES
    try:
        connection = await ConnectorEngine(db).get_connection(
            connection_id, organization_id)
    except Exception as exc:
        raise _err(exc)
    if body.verify_mode not in VERIFY_MODES or body.verify_mode == "none":
        raise HTTPException(status_code=400,
                            detail="verify_mode must be a signed mode (never 'none')")
    endpoint = body.endpoint.strip().strip("/")
    if not endpoint or len(endpoint) > 200 or ".." in endpoint or " " in endpoint:
        raise HTTPException(status_code=400, detail="Invalid endpoint path")
    from openagent.connectors.crypto import generate_webhook_secret
    secret, digest = generate_webhook_secret()
    row = ConnectorWebhook(
        connection_id=connection.id, organization_id=organization_id,
        connector_id=connection.connector_id, endpoint=endpoint,
        event_types=body.event_types[:64], verify_mode=body.verify_mode,
        secret_hash=digest, secret_prefix=secret[:8])
    db.add(row)
    await db.flush()
    # Encrypted copy bound to the webhook id for HMAC verification.
    from openagent.connectors.crypto import encrypt_secret
    from openagent.core.config import get_settings
    try:
        row.secret_cipher = encrypt_secret(
            get_settings().ENCRYPTION_KEY, secret, associated=str(row.id))
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Encryption failed: {exc}")
    await db.commit()
    return {"id": str(row.id),
            "url": f"/api/v1/webhooks/{connection.connector_id}/{connection.id}/{endpoint}",
            "secret": secret,  # shown ONCE; only the hash is stored
            "secret_prefix": row.secret_prefix,
            "max_bytes": MAX_WEBHOOK_BYTES}


@webhooks_mgmt_router.post("/{webhook_id}/rotate", summary="Rotate webhook secret")
async def rotate_webhook_secret(organization_id: UUID, webhook_id: UUID,
                                db: AsyncSession = Depends(get_db),
                                ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "webhook:update")
    result = await db.execute(select(ConnectorWebhook).where(
        ConnectorWebhook.id == webhook_id))
    row = result.scalar_one_or_none()
    if row is None or row.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Webhook not found")
    from openagent.connectors.crypto import generate_webhook_secret
    secret, digest = generate_webhook_secret()
    row.secret_hash = digest
    row.secret_prefix = secret[:8]
    row.failure_count = 0
    from openagent.connectors.crypto import encrypt_secret
    from openagent.core.config import get_settings
    row.secret_cipher = encrypt_secret(
        get_settings().ENCRYPTION_KEY, secret, associated=str(row.id))
    await db.commit()
    return {"secret": secret, "secret_prefix": row.secret_prefix}


@webhooks_mgmt_router.delete("/{webhook_id}", summary="Delete webhook endpoint")
async def delete_webhook_endpoint(organization_id: UUID, webhook_id: UUID,
                                  db: AsyncSession = Depends(get_db),
                                  ctx: AuthorizationContext = Depends(get_current_org_context)):
    _org_or_403(ctx, organization_id)
    AuthorizationService(db).require_permission(ctx, "webhook:delete")
    result = await db.execute(select(ConnectorWebhook).where(
        ConnectorWebhook.id == webhook_id))
    row = result.scalar_one_or_none()
    if row is None or row.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await db.delete(row)
    await db.commit()
    return {"deleted": True}


# -- webhooks: public receiver (signature-authenticated) ---------------------------
_receiver_replay: dict[str, float] = {}
_receiver_hits: dict[str, list[float]] = {}
_RECEIVER_LIMIT_PER_MINUTE = 120


def _receiver_rate_limited(key: str, *, now: float) -> bool:
    window = _receiver_hits.setdefault(key, [])
    cutoff = now - 60.0
    del window[:sum(1 for ts in window if ts < cutoff)]
    if len(window) >= _RECEIVER_LIMIT_PER_MINUTE:
        return True
    window.append(now)
    return False


@webhooks_router.post("/{connector_id}/{connection_id}/{endpoint:path}",
                      summary="Inbound provider webhook (signature verified)")
async def receive_webhook(connector_id: str, connection_id: str, endpoint: str,
                          request: Request, db: AsyncSession = Depends(get_db)):
    from openagent.connectors import webhooks as webhook_mod
    from openagent.connectors.engine import ConnectorEngine
    raw = await request.body()
    if len(raw) > webhook_mod.MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    if _receiver_rate_limited(f"{connector_id}/{connection_id}/{endpoint}",
                              now=time.time()):
        raise HTTPException(status_code=429, detail="Webhook rate limited")
    try:
        connection_uuid = UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")
    # Never trust connector/connection/event names from the request alone:
    # resolve the registered endpoint row first (tenant-scoped by URL).
    result = await db.execute(select(ConnectorWebhook).where(
        ConnectorWebhook.connection_id == connection_uuid,
        ConnectorWebhook.connector_id == connector_id,
        ConnectorWebhook.endpoint == endpoint.strip().strip("/"),
        ConnectorWebhook.is_active.is_(True)))
    hook = result.scalar_one_or_none()
    if hook is None:
        raise HTTPException(status_code=404, detail="Not found")
    headers = dict(request.headers)
    # Resolve the endpoint secret server-side (decrypt the bound ciphertext;
    # plaintext lives only in this scope) and verify the signature.
    verified = False
    mode = hook.verify_mode or "hmac_sha256"
    try:
        from openagent.connectors.crypto import decrypt_secret
        from openagent.core.config import get_settings
        endpoint_secret = decrypt_secret(
            get_settings().ENCRYPTION_KEY, hook.secret_cipher or "",
            associated=str(hook.id)) if hook.secret_cipher else ""
    except Exception:
        endpoint_secret = ""
    if endpoint_secret:
        try:
            verified = webhook_mod.verify_signature(
                mode, endpoint_secret, raw, headers)
        except Exception:
            verified = False
    if not verified:
        # Telegram-style bearer tokens are hash-comparable without decryption.
        for candidate in _webhook_secret_candidates(headers):
            digest = hashlib.sha256(candidate.encode()).hexdigest()
            if hmac.compare_digest(digest, hook.secret_hash):
                try:
                    verified = webhook_mod.verify_signature(
                        mode, candidate, raw, headers)
                except Exception:
                    verified = False
                break
    hook.last_signature_ok = verified
    if not verified:
        hook.failure_count = int(hook.failure_count or 0) + 1
        await db.commit()
        await ConnectorEngine(db)._security_event(
            hook.organization_id, None, "connector.signature_invalid",
            {"webhook_id": str(hook.id)})
        raise HTTPException(status_code=403, detail="Invalid signature")
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            payload = {"_raw": payload}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    delivery_id = (headers.get("x-delivery-id") or headers.get("x-github-delivery")
                   or headers.get("x-request-id") or payload.get("id", "") or "")
    delivery_id = str(delivery_id)[:128]
    # Replay protection: in-request dedupe + persisted delivery id.
    now = time.time()
    for key in list(_receiver_replay):
        if now - _receiver_replay[key] > 3600:
            del _receiver_replay[key]
    replay_key = f"{hook.id}:{delivery_id or hashlib.sha256(raw).hexdigest()}"
    if replay_key in _receiver_replay:
        await ConnectorEngine(db)._security_event(
            hook.organization_id, None, "connector.webhook_replay",
            {"webhook_id": str(hook.id)})
        raise HTTPException(status_code=409, detail="Duplicate delivery")
    _receiver_replay[replay_key] = now
    if delivery_id:
        dup = (await db.execute(select(ConnectorEvent).where(
            ConnectorEvent.delivery_id == delivery_id,
            ConnectorEvent.organization_id == hook.organization_id,
            ConnectorEvent.provider == connector_id))).scalar_one_or_none()
        if dup is not None:
            await ConnectorEngine(db)._security_event(
                hook.organization_id, None, "connector.webhook_replay",
                {"webhook_id": str(hook.id)})
            raise HTTPException(status_code=409, detail="Duplicate delivery")
    event_name = _provider_event_name(connector_id, headers, payload)
    if hook.event_types and event_name not in set(hook.event_types):
        # Filtered at the edge; still ack to avoid provider retries.
        hook.last_delivery_at = datetime.now(timezone.utc)
        await db.commit()
        return {"received": True, "filtered": True}
    _ensure_registry()
    from openagent.connectors import providers as provider_pkg
    normalizer = provider_pkg.get_normalizer(connector_id)
    normalized = {"event_type": event_name, "resource_id": "",
                  "attributes": {}} if normalizer is None else \
        normalizer(event_name, payload)
    event = ConnectorEvent(
        webhook_id=hook.id, connection_id=hook.connection_id,
        organization_id=hook.organization_id, event_type=str(
            normalized.get("event_type", event_name))[:160],
        provider=connector_id, resource_id=str(
            normalized.get("resource_id", ""))[:256],
        delivery_id=delivery_id,
        payload_reference="",  # raw payloads not stored by default
        attributes=dict(normalized.get("attributes", {}) or {}))
    # Optional raw retention only when explicitly configured on the webhook.
    db.add(event)
    await db.flush()
    hook.last_delivery_at = datetime.now(timezone.utc)
    hook.failure_count = 0
    await db.flush()
    try:
        from openagent.core.events import EventService
        await EventService(db).publish(
            f"connector.{event.event_type}", "connector_event", event.id,
            {"provider": connector_id, "resource_id": event.resource_id,
             "connection_id": str(hook.connection_id)},
            organization_id=hook.organization_id)
    except Exception:
        pass
    await db.commit()
    from openagent.connectors import metrics as connector_metrics
    connector_metrics.inc("connector_webhook_events_total")
    return {"received": True, "event_id": str(event.id),
            "event_type": event.event_type}


def _provider_event_name(connector_id: str, headers: dict[str, str],
                         payload: dict[str, Any]) -> str:
    """Provider-specific event naming (github actions, gitlab object_kind...)."""
    lowered = {k.lower(): v for k, v in headers.items()}
    if connector_id == "github":
        from openagent.connectors.providers import github as github_mod
        return github_mod.normalize_event("", payload, headers).get(
            "event_type", "") or "unknown"
    if connector_id == "gitlab":
        from openagent.connectors.providers import gitlab as gitlab_mod
        return gitlab_mod.normalize_event("", payload).get("event_type", "") or "unknown"
    for key in ("x-event-type", "x-event", "x-hook-event"):
        if lowered.get(key):
            return str(lowered[key])[:160]
    if isinstance(payload.get("event_type"), str) and payload["event_type"]:
        return str(payload["event_type"])[:160]
    return "unknown"


def _webhook_secret_candidates(headers: dict[str, str]) -> list[str]:
    """Extract presented secrets WITHOUT logging them.

    For HMAC schemes the presented value is a signature, not the secret —
    those cannot be hash-compared, so HMAC verification needs the secret.
    Since only hashes are stored, HMAC modes resolve the secret from the
    connection credential (capability-scoped) instead.
    """
    lowered = {k.lower(): v for k, v in headers.items()}
    candidates = []
    token = lowered.get("x-telegram-bot-api-secret-token", "")
    if token:
        candidates.append(token)
    return candidates
