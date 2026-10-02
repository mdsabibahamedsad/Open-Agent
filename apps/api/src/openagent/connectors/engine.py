"""Connector execution engine (MP21).

Full pipeline per action — External Service -> Connector Definition ->
Authentication -> Credential Resolution -> Connection -> Capability Registry ->
Tool/Trigger/Resource -> Policy -> RBAC -> Risk/Approval -> Tool Runtime ->
Execution -> Verification -> Audit. No privileged action executes outside it.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.connectors import metrics as connector_metrics
from openagent.connectors.crypto import decrypt_secret
from openagent.connectors.http_client import ProviderHTTPClient, shared_client
from openagent.connectors.types import ConnectorExecutionContext

logger = structlog.get_logger("openagent.connectors.engine")


class ConnectorError(Exception):
    def __init__(self, message: str, code: str = "CONNECTOR_ERROR"):
        super().__init__(message)
        self.code = code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConnectorEngine:
    """DB-backed execution engine. Provider logic lives in providers/ modules
    behind a uniform interface; this class owns tenancy, policy, and audit."""

    def __init__(self, db: AsyncSession,
                 http: Optional[ProviderHTTPClient] = None):
        self.db = db
        self.http = http or shared_client()

    # -- connection + credential resolution ----------------------------------
    async def get_connection(self, connection_id: UUID,
                             organization_id: UUID) -> Any:
        from openagent.db.models.connector import ConnectorConnection
        result = await self.db.execute(
            select(ConnectorConnection).where(
                ConnectorConnection.id == connection_id))
        connection = result.scalar_one_or_none()
        if connection is None or connection.organization_id != organization_id:
            await self._security_event(organization_id, None,
                                       "connector.cross_tenant_attempt",
                                       {"connection_id": str(connection_id)})
            raise ConnectorError("Connection not found", code="NOT_FOUND")
        return connection

    def check_sharing(self, connection: Any, *, user_id: Optional[UUID] = None,
                      team_ids: Optional[list[str]] = None,
                      workflow_id: Optional[UUID] = None) -> None:
        """Enforce PRIVATE/TEAM/ORGANIZATION/WORKFLOW_ONLY sharing."""
        policy = str(getattr(connection, "sharing_policy", "PRIVATE") or "PRIVATE")
        # Normalize DB lowercase values and enum members alike.
        policy = getattr(getattr(connection, "sharing_policy", None), "value",
                         policy).upper()
        if policy == "ORGANIZATION":
            return
        if policy == "PRIVATE":
            owner = str(getattr(connection, "owner_user_id", "") or "")
            if not user_id or str(user_id) != owner:
                raise ConnectorError("Connection is private to its owner",
                                     code="SHARING_DENIED")
            return
        if policy == "TEAM":
            allowed = set(getattr(connection, "team_ids", []) or [])
            if not (set(team_ids or []) & allowed):
                raise ConnectorError("Connection not shared with your team",
                                     code="SHARING_DENIED")
            return
        if policy == "WORKFLOW_ONLY":
            allowed = set(getattr(connection, "workflow_ids", []) or [])
            if not workflow_id or str(workflow_id) not in allowed:
                raise ConnectorError("Connection restricted to bound workflows",
                                     code="SHARING_DENIED")
            return
        raise ConnectorError(f"Unknown sharing policy '{policy}'",
                             code="SHARING_DENIED")

    async def resolve_credential(self, connection: Any) -> dict[str, Any]:
        """Decrypt capability-scoped credential. Returns auth bundle, and the
        plaintext lives only in this return value (never logged/stored)."""
        from openagent.core.config import get_settings
        from openagent.db.models.credential import Credential, CredentialStatus
        credential_id = getattr(connection, "credential_id", None)
        if credential_id is None:
            raise ConnectorError("Connection has no credential", code="NO_CREDENTIAL")
        result = await self.db.execute(
            select(Credential).where(Credential.id == credential_id))
        credential = result.scalar_one_or_none()
        if credential is None or \
                credential.organization_id != connection.organization_id:
            raise ConnectorError("Credential not found", code="NO_CREDENTIAL")
        if credential.status != CredentialStatus.ACTIVE:
            raise ConnectorError(f"Credential is {credential.status.value}",
                                 code="CREDENTIAL_INACTIVE")
        settings = get_settings()
        try:
            payload = decrypt_secret(
                settings.ENCRYPTION_KEY, credential.encrypted_data,
                associated=str(credential.id))
        except Exception as exc:
            await self._security_event(connection.organization_id, None,
                                       "connector.credential_failure",
                                       {"connection_id": str(connection.id)})
            raise ConnectorError(f"Credential decrypt failed: {exc}",
                                 code="CREDENTIAL_DECRYPT_FAILED") from exc
        import json
        try:
            data = json.loads(payload) if isinstance(payload, str) else dict(payload)
        except Exception:
            data = {"secret": payload}
        if not isinstance(data, dict):
            data = {"secret": data}
        refreshed = await self._refresh_oauth_if_expired(
            connection=connection, credential=credential, data=data)
        if refreshed is not None:
            data = refreshed
        return {"credential_id": str(credential.id),
                "credential_type": str(credential.credential_type.value
                                       if hasattr(credential.credential_type, "value")
                                       else credential.credential_type),
                "secrets": data if isinstance(data, dict) else {"secret": data},
                "expires_at": credential.expires_at.isoformat()
                if credential.expires_at else None}

    async def _refresh_oauth_if_expired(self, *, connection: Any,
                                        credential: Any,
                                        data: dict[str, Any]) -> dict[str, Any] | None:
        """Attempt a single OAuth refresh when the stored token is expired and
        a refresh_token is available. Returns the new secrets dict, or None
        when no refresh applies. Never logs token material."""
        try:
            from datetime import datetime, timezone as _tz

            expires_at = getattr(credential, "expires_at", None)
            if expires_at is None:
                return None
            now = datetime.now(_tz.utc)
            exp = expires_at if expires_at.tzinfo is not None \
                else expires_at.replace(tzinfo=_tz.utc)
            if (exp - now).total_seconds() > 60:
                return None
            refresh_token = str(data.get("refresh_token", "") or "")
            if not refresh_token:
                raise ConnectorError("Credential expired; reconnect required",
                                     code="AUTH_EXPIRED")
            from openagent.connectors.oauth import OAuthConfig, OAuthManager
            manifest_auth: dict[str, Any] = {}
            try:
                from openagent.connectors.registry import registry
                manifest = registry.get(str(connection.connector_id))
                if manifest is not None:
                    manifest_auth = dict(getattr(manifest, "auth", {}) or {})
            except Exception:
                manifest_auth = {}
            token_url = str(manifest_auth.get("token_url", "") or "")
            authorize_url = str(manifest_auth.get("authorize_url", "") or "")
            client_id = str(data.get("client_id", "") or
                            manifest_auth.get("client_id", "") or "")
            client_secret = str(data.get("client_secret", "") or "")
            if not token_url.startswith("https://"):
                raise ConnectorError("Credential expired; reconnect required",
                                     code="AUTH_EXPIRED")
            manager = OAuthManager(OAuthConfig(
                authorize_url=authorize_url or token_url,
                token_url=token_url, client_id=client_id,
                redirect_uri=str(data.get("redirect_uri", "") or "")))

            async def _post_form(url: str, fields: dict[str, str],
                                 secrets_map: dict[str, str]):
                from openagent.connectors.netsec import assert_url_safe
                assert_url_safe(url)
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                            url, data={**fields,
                                       **{k: v for k, v in secrets_map.items()}},
                            timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        try:
                            body = await resp.json()
                        except Exception:
                            body = {}
                        return resp.status, body if isinstance(body, dict) else {}

            tokens = await manager.refresh(
                refresh_token=refresh_token, client_secret=client_secret,
                post_form=_post_form)
            new_data = dict(data)
            new_data["access_token"] = tokens.access_token
            if tokens.refresh_token:
                new_data["refresh_token"] = tokens.refresh_token
            if tokens.expires_in:
                from datetime import timedelta
                credential.expires_at = now + timedelta(seconds=tokens.expires_in)
            from openagent.connectors.crypto import encrypt_secret
            from openagent.core.config import get_settings
            import json as _json
            settings = get_settings()
            credential.encrypted_data = encrypt_secret(
                settings.ENCRYPTION_KEY, _json.dumps(new_data),
                associated=str(credential.id))
            await self.db.flush()
            await self._audit(connection.organization_id,
                              "connector.credential_rotated",
                              "credential", credential.id,
                              {"connection_id": str(connection.id),
                               "reason": "oauth_refresh"})
            return new_data
        except ConnectorError:
            raise
        except Exception as exc:
            logger.warning("oauth refresh failed", error=str(exc)[:120])
            return None

    # -- policy ---------------------------------------------------------------
    async def _resolve_team_ids(self, organization_id: UUID,
                                user_id: Any | None,
                                caller_claimed: list[str]) -> list[str]:
        """Server-side team membership. Caller claims are only honored when
        they intersect verified membership (poll/system contexts may carry
        none, which yields [])."""
        if user_id is None:
            return []
        try:
            from openagent.db.models.team import Team, TeamMembership
            rows = (await self.db.execute(select(TeamMembership).join(
                Team, Team.id == TeamMembership.team_id).where(
                    Team.organization_id == organization_id,
                    TeamMembership.user_id == user_id))).scalars().all()
            verified = {str(getattr(r, "team_id", "")) for r in rows
                        if getattr(r, "team_id", None)}
            if verified:
                claimed = set(caller_claimed or [])
                return sorted(verified if not claimed else verified & claimed
                              or verified)
            return []
        except Exception as exc:
            logger.warning("team resolution skipped", error=str(exc)[:120])
            return []

    def check_connector_policy(self, *, manifest: Any, action: Any,
                               connection: Any,
                               granted_capabilities: list[str]) -> None:
        """Least-privilege: action capabilities must be granted on the
        connection; instance allow/deny lists apply on top."""
        missing = [c for c in (action.required_capabilities or [])
                   if c not in set(granted_capabilities or [])]
        if missing:
            raise ConnectorError(
                f"Missing capabilities: {', '.join(missing)}", code="CAPABILITY_DENIED")
        config = getattr(connection, "policy_config", None) or {}
        denied = set(config.get("deny_actions", []) or [])
        if action.id in denied or "*" in denied:
            raise ConnectorError(f"Action '{action.id}' denied by connector policy",
                                 code="POLICY_DENIED")
        allowed = config.get("allow_actions")
        if allowed is not None and action.id not in set(allowed):
            raise ConnectorError(f"Action '{action.id}' not in connector allow-list",
                                 code="POLICY_DENIED")

    # -- risk + approval (MP19, never bypassed) ---------------------------------
    async def gate_action(self, *, manifest: Any, action: Any,
                          organization_id: UUID,
                          arguments: dict[str, Any],
                          context: ConnectorExecutionContext,
                          approval_id: Optional[UUID] = None) -> Optional[Any]:
        """Run policy -> risk -> approval. Returns None when execution may
        proceed, or the parked approval when human review is required.
        Raises on DENY / invalid approval."""
        from openagent.approvals.integrations import (
            consume_approval,
            load_org_policies,
            park_for_approval,
        )
        from openagent.approvals.policy import evaluate_policies
        from openagent.approvals.risk import evaluate_risk
        from openagent.approvals.types import ActionContext, ApprovalKind, PolicyDecision
        trust = manifest.trust.value if hasattr(manifest.trust, "value") \
            else str(manifest.trust)
        tool_trust = trust if trust in ("CORE", "VERIFIED", "ORGANIZATION") \
            else "UNTRUSTED"  # community/custom never elevated
        ctype = manifest.connector_type.value \
            if hasattr(manifest.connector_type, "value") \
            else str(manifest.connector_type)
        mcp_trust = tool_trust if ctype == "MCP_BACKED" else tool_trust
        destructive = any(w in action.id.lower()
                          for w in ("delete", "destroy", "drop", "remove"))
        financial = manifest.category == "finance" or "payment" in action.id.lower()
        external = action.mutation
        actx = ActionContext(
            action_type=action.id, action_category="WRITE",
            target_type="connector", target_id=manifest.id,
            target_reference=f"{manifest.id}.{action.id}"[:256],
            environment="production" if "production" in manifest.supported_environments
            else "development",
            params_summary={k: str(v)[:256] for k, v in (arguments or {}).items()},
            external_side_effect=external, financial_impact=financial,
            destructive=destructive, credential_usage=False,
            network_access=True, tenant_scope="organization",
            organization_id=str(organization_id),
            agent_trust="ORGANIZATION", tool_trust=tool_trust,
            mcp_trust=mcp_trust, tool_name=action.id)
        # Unknown custom API mutations default HIGH until policy says otherwise.
        if ctype == "HTTP_GENERIC" and action.mutation:
            actx.destructive = actx.destructive or True
        risk = evaluate_risk(actx)
        # Manifest-declared risk can only escalate, never de-escalate.
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        declared = order.get(action.risk_level.value
                             if hasattr(action.risk_level, "value")
                             else str(action.risk_level), 1)
        current = order.get(risk.risk_level.value, 1)
        if declared > current:
            from openagent.approvals.types import RiskLevel
            names = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
            risk.risk_level = RiskLevel(names[declared])
            risk.reasons.append(f"Connector-declared risk {names[declared]}")
        policies = await load_org_policies(self.db, organization_id)
        evaluation = evaluate_policies(ctx=actx, risk=risk,
                                       policies_by_level=policies)
        if evaluation.decision == PolicyDecision.DENY:
            raise ConnectorError(
                f"Denied by policy: {'; '.join(evaluation.reasons[:3])}",
                code="POLICY_DENIED")
        if evaluation.decision in (PolicyDecision.REQUIRE_APPROVAL,
                                   PolicyDecision.REQUIRE_MULTI_APPROVAL,
                                   PolicyDecision.REQUIRE_ESCALATION):
            if approval_id is None:
                approval = await park_for_approval(
                    self.db, organization_id=organization_id,
                    action_type=action.id, action_category="WRITE",
                    target_type="connector", target_id=manifest.id,
                    params=arguments, environment=actx.environment,
                    requester_type="agent",
                    requester_id=context.agent_id or None,
                    risk=risk, evaluation=evaluation,
                    approval_kind=(ApprovalKind.MULTI if evaluation.decision
                                    == PolicyDecision.REQUIRE_MULTI_APPROVAL
                                    else ApprovalKind.SINGLE),
                    required_approvals=evaluation.required_approvals,
                    required_role=evaluation.required_role)
                connector_metrics.inc("approval_gates_total")
                return approval
            ok, reason = await consume_approval(
                self.db, approval_id=approval_id, organization_id=organization_id,
                action_type=action.id, action_category="WRITE",
                target_type="connector", target_id=manifest.id,
                params=arguments, environment=actx.environment)
            if not ok:
                raise ConnectorError(f"Approval invalid: {reason}",
                                     code="INVALID_APPROVAL")
        return None

    # -- execution ---------------------------------------------------------------
    async def execute_action(self, *, connector_id: str, action_id: str,
                             connection_id: UUID, organization_id: UUID,
                             arguments: dict[str, Any],
                             context: Optional[ConnectorExecutionContext] = None,
                             approval_id: Optional[UUID] = None,
                             idempotency_key: str = "") -> dict[str, Any]:
        """Execute one connector action through the full pipeline."""
        from openagent.connectors.registry import registry
        started = time.time()
        manifest = registry.get(connector_id)
        if manifest is None:
            raise ConnectorError(f"Unknown connector '{connector_id}'",
                                 code="NOT_FOUND")
        self._enforce_version_pin(connection=None, manifest=manifest,
                                  connector_id=connector_id)
        action = next((a for a in manifest.actions if a.id == action_id), None)
        if action is None:
            raise ConnectorError(f"Unknown action '{action_id}'", code="NOT_FOUND")
        connection = await self.get_connection(connection_id, organization_id)
        self._enforce_version_pin(connection=connection, manifest=manifest,
                                  connector_id=connector_id)
        if str(getattr(connection, "connector_id", "") or "") not in ("", connector_id):
            raise ConnectorError("Connection belongs to another connector",
                                 code="CONNECTION_MISMATCH")
        ctx = context or ConnectorExecutionContext(
            organization_id=str(organization_id), connector_id=connector_id,
            connection_id=str(connection_id))
        try:
            sharing_user = UUID(ctx.user_id) if ctx.user_id else None
        except ValueError:
            sharing_user = None
        try:
            sharing_workflow = UUID(ctx.workflow_id) if ctx.workflow_id else None
        except ValueError:
            sharing_workflow = None
        policy_ctx = ctx.policy_context or {}
        team_ids = await self._resolve_team_ids(
            organization_id, sharing_user,
            caller_claimed=[str(t) for t in
                            policy_ctx.get("team_ids", []) or []])
        self.check_sharing(connection, user_id=sharing_user,
                           team_ids=team_ids,
                           workflow_id=sharing_workflow)
        auth = await self.resolve_credential(connection)
        granted = list(getattr(connection, "granted_capabilities", []) or [])
        granted = await self._merge_permission_grants(connection, granted)
        self.check_connector_policy(manifest=manifest, action=action,
                                    connection=connection,
                                    granted_capabilities=granted)
        # Validate input BEFORE parking an approval so invalid payloads never
        # burn a human-review ticket.
        self._validate_input(action, arguments)
        parked = await self.gate_action(
            manifest=manifest, action=action, organization_id=organization_id,
            arguments=arguments, context=ctx, approval_id=approval_id)
        if parked is not None:
            await self._audit(organization_id, "connector.approval_parked",
                              "connector_connection", connection.id,
                              {"action": action_id})
            return {"status": "WAITING_FOR_APPROVAL",
                    "approval_id": str(parked.id),
                    "action": action_id}
        await self._enforce_rate_and_quota(
            connection=connection, action=action, organization_id=organization_id)
        outcome = await self._dispatch(manifest=manifest, action=action,
                                       arguments=arguments, auth=auth,
                                       connection=connection, ctx=ctx,
                                       idempotency_key=idempotency_key)
        latency_ms = int((time.time() - started) * 1000)
        await self._after_execution(
            manifest=manifest, action=action, connection=connection,
            organization_id=organization_id, arguments=arguments,
            outcome=outcome, latency_ms=latency_ms, ctx=ctx)
        return outcome

    def _validate_input(self, action: Any, arguments: dict[str, Any]) -> None:
        from openagent.evaluator.deterministic import validate_json_schema
        schema = action.input_schema or {"type": "object"}
        violations = validate_json_schema(arguments or {}, schema)
        if violations:
            raise ConnectorError(f"Invalid input: {'; '.join(violations[:3])}",
                                 code="VALIDATION_ERROR")

    @staticmethod
    def _enforce_version_pin(*, connection: Any | None,
                             manifest: Any, connector_id: str) -> None:
        """Pinned execution: a connection bound to connector@X.Y.Z keeps that
        contract. Major-version drift is rejected; minor/patch drift proceeds
        (registry keeps one manifest/id) but is surfaced for migration."""
        pinned = str(getattr(connection, "connector_version", "") or "") \
            if connection is not None else ""
        if not pinned:
            return
        current = str(getattr(manifest, "version", "") or "")
        if not current or pinned == current:
            return
        try:
            pinned_major = int(str(pinned).split(".")[0])
            current_major = int(str(current).split(".")[0])
        except (ValueError, IndexError):
            raise ConnectorError(
                f"Connection pinned to unreadable version '{pinned}'",
                code="VERSION_MISMATCH")
        if pinned_major != current_major:
            raise ConnectorError(
                f"Connection pinned to {connector_id}@{pinned} but registry "
                f"serves @{current}; migrate the workflow explicitly",
                code="VERSION_MISMATCH")
        logger.warning("connector version drift",
                       connector=connector_id, pinned=pinned, current=current)

    async def _merge_permission_grants(self, connection: Any,
                                       granted: list[str]) -> list[str]:
        """Merge fine-grained ConnectorPermission rows into the effective
        capability set. Connection.granted_capabilities remains the base;
        rows grant additional capabilities to their grantee scope."""
        merged = set(granted or [])
        try:
            from openagent.db.models.connector import ConnectorPermission
            result = await self.db.execute(
                select(ConnectorPermission).where(
                    ConnectorPermission.connection_id == connection.id))
            for row in result.scalars().all():
                for cap in (getattr(row, "capabilities", None) or []):
                    if isinstance(cap, str) and cap:
                        merged.add(cap)
        except Exception as exc:
            logger.warning("connector permission merge skipped", error=str(exc))
        return sorted(merged)

    # Per-process sliding-window guards so declared per-action limits and the
    # platform quota actually gate execution (durable usage stays in DB).
    _rate_windows: dict[tuple[str, str], list[float]] = {}
    _quota_windows: dict[str, list[float]] = {}

    async def _enforce_rate_and_quota(self, *, connection: Any, action: Any,
                                      organization_id: UUID) -> None:
        import time as _time

        from openagent.connectors import ratelimit as _ratelimits
        from openagent.connectors.config import get_connector_settings
        now = _time.time()
        per_minute = int(getattr(action, "rate_limit_per_minute", 60) or 60)
        key = (str(connection.id), str(getattr(action, "id", "")))
        window = self._rate_windows.setdefault(key, [])
        cutoff = now - 60.0
        while window and window[0] <= cutoff:
            window.pop(0)
        if len(window) >= max(1, per_minute):
            from openagent.connectors import metrics as _metrics
            _metrics.inc("connector_rate_limited_total")
            raise ConnectorError(
                f"Rate limit exceeded for '{action.id}' ({per_minute}/min)",
                code="RATE_LIMITED")
        window.append(now)
        # Provider-header cooperation is preserved for the HTTP layer; here we
        # enforce the declared floor even before any provider headers arrive.
        state = _ratelimits.RateLimitState(configured_per_minute=per_minute)
        decision = _ratelimits.check(state, strategy="fail")
        if not decision.allowed:
            raise ConnectorError(f"Rate limited: {decision.reason}",
                                 code="RATE_LIMITED")
        try:
            from openagent.connectors.config import ConnectorSettings
            quota = int(ConnectorSettings().CONNECTOR_QUOTA_PER_MINUTE or 120)
        except Exception:
            quota = 120
        qkey = str(connection.id)
        qwindow = self._quota_windows.setdefault(qkey, [])
        while qwindow and qwindow[0] <= cutoff:
            qwindow.pop(0)
        if len(qwindow) >= max(1, quota):
            from openagent.connectors import metrics as _metrics
            _metrics.inc("connector_rate_limited_total")
            raise ConnectorError("Connector quota exhausted, try again shortly",
                                 code="RATE_LIMITED")
        qwindow.append(now)

    async def _dispatch(self, *, manifest: Any, action: Any,
                        arguments: dict[str, Any], auth: dict[str, Any],
                        connection: Any, ctx: ConnectorExecutionContext,
                        idempotency_key: str) -> dict[str, Any]:
        connector_metrics.inc("connector_calls_total")
        dispatch_ctx = {"http": self.http, "logger": logger,
                        "idempotency_key": idempotency_key,
                        "connector_id": manifest.id,
                        "connection": {"id": str(connection.id),
                                       "connector_id": manifest.id,
                                       "config": dict(getattr(connection, "config", {}) or {})}}
        if str(manifest.connector_type.value
               if hasattr(manifest.connector_type, "value")
               else manifest.connector_type) == "DATABASE":
            from openagent.connectors import db_connector
            return await db_connector.execute(
                manifest=manifest, action=action, arguments=arguments,
                auth=auth, ctx=dispatch_ctx)
        from openagent.connectors import providers as provider_pkg
        executor = provider_pkg.get_executor(manifest.id)
        if executor is None:
            # Generic HTTP fallback for declarative HTTP_GENERIC/CUSTOM
            # manifests (no custom code needed).
            ctype = str(manifest.connector_type.value
                        if hasattr(manifest.connector_type, "value")
                        else manifest.connector_type)
            if ctype in ("HTTP_GENERIC", "CUSTOM"):
                from openagent.connectors.providers import http_generic
                try:
                    return await http_generic.execute_generic(
                        manifest, action.id, dict(arguments), auth,
                        dispatch_ctx)
                except Exception as exc:
                    from openagent.connectors.errors import ProviderError
                    if isinstance(exc, ProviderError):
                        raise
                    connector_metrics.inc("connector_failure_total")
                    raise ConnectorError(
                        f"Provider execution failed: {exc}",
                        code="EXECUTION_FAILED") from exc
            raise ConnectorError(f"No executor for connector '{manifest.id}'",
                                 code="NO_EXECUTOR")
        try:
            return await executor(action.id, dict(arguments), auth, dispatch_ctx)
        except Exception as exc:
            from openagent.connectors.errors import ProviderError
            if isinstance(exc, ProviderError):
                raise
            connector_metrics.inc("connector_failure_total")
            raise ConnectorError(f"Provider execution failed: {exc}",
                                 code="EXECUTION_FAILED") from exc

    async def _after_execution(self, *, manifest: Any, action: Any,
                               connection: Any, organization_id: UUID,
                               arguments: dict[str, Any], outcome: dict[str, Any],
                               latency_ms: int, ctx: ConnectorExecutionContext) -> None:
        status = str(outcome.get("status", "ok"))
        if status in ("ok", "success", "succeeded"):
            connector_metrics.inc("connector_success_total")
        else:
            connector_metrics.inc("connector_failure_total")
        # Evaluator hook for mutations: provider response -> verification.
        if action.mutation:
            try:
                from openagent.evaluator.integrations import verify_tool_call
                await verify_tool_call(
                    self.db, organization_id=organization_id,
                    tool_name=action.id, result=outcome,
                    independently_verified=bool(
                        outcome.get("verified") or outcome.get("id")),
                    agent_id=UUID(ctx.agent_id) if ctx.agent_id else None)
            except Exception as exc:
                logger.warning("connector evaluation hook skipped", error=str(exc))
        await self._record_usage(connection, action, latency_ms,
                                 success=status in ("ok", "success", "succeeded"))
        await self._audit(organization_id, "connector.action_executed",
                          "connector_connection", connection.id,
                          {"connector": manifest.id, "action": action.id,
                           "status": status, "latency_ms": latency_ms,
                           "provider_request_id": str(
                               outcome.get("provider_request_id", ""))[:128]})
        try:
            from openagent.core.events import EventService
            await EventService(self.db).publish(
                "connector.action_executed", "connector_connection",
                connection.id,
                {"connector": manifest.id, "action": action.id, "status": status},
                organization_id=organization_id)
        except Exception as exc:
            logger.warning("connector event skipped", error=str(exc))

    async def _record_usage(self, connection: Any, action: Any,
                            latency_ms: int, success: bool) -> None:
        try:
            from datetime import date

            from openagent.db.models.connector import ConnectorUsage
            today = date.today().isoformat()
            result = await self.db.execute(
                select(ConnectorUsage).where(
                    ConnectorUsage.connection_id == connection.id,
                    ConnectorUsage.period == today))
            row = result.scalar_one_or_none()
            if row is None:
                row = ConnectorUsage(connection_id=connection.id,
                                     organization_id=connection.organization_id,
                                     period=today, calls=0, successes=0,
                                     failures=0, latency_ms_total=0)
                self.db.add(row)
            row.calls = int(row.calls or 0) + 1
            if success:
                row.successes = int(row.successes or 0) + 1
            else:
                row.failures = int(row.failures or 0) + 1
            row.latency_ms_total = int(row.latency_ms_total or 0) + latency_ms
            await self.db.flush()
        except Exception as exc:
            logger.warning("connector usage skipped", error=str(exc))

    # -- connection lifecycle ------------------------------------------------------
    async def test_connection(self, connection_id: UUID,
                              organization_id: UUID) -> dict[str, Any]:
        """Minimal safe, non-mutating connection test."""
        from openagent.connectors.registry import registry
        connection = await self.get_connection(connection_id, organization_id)
        manifest = registry.get(str(connection.connector_id))
        if manifest is None:
            raise ConnectorError("Connector definition missing", code="NOT_FOUND")
        auth = await self.resolve_credential(connection)
        from openagent.connectors import providers as provider_pkg
        tester = provider_pkg.get_tester(str(connection.connector_id))
        use_generic_tester = False
        if tester is None:
            ctype = str(manifest.connector_type.value
                        if hasattr(manifest.connector_type, "value")
                        else manifest.connector_type)
            if ctype in ("HTTP_GENERIC", "CUSTOM"):
                from openagent.connectors.providers import http_generic
                tester = http_generic.test_generic
                use_generic_tester = True
        if tester is None:
            return {"ok": True, "skipped": True,
                    "message": "No provider test; credential decrypts and policy passes"}
        try:
            test_ctx = {"http": self.http, "logger": logger,
                        "connector_id": str(connection.connector_id),
                        "connection": {"id": str(connection.id),
                                       "connector_id": str(connection.connector_id)}}
            if use_generic_tester:
                detail = await tester(manifest, auth, test_ctx)
            else:
                detail = await tester(auth, test_ctx)
            return {"ok": True, "detail": detail}
        except Exception as exc:
            # Never persist or return driver/provider internals (DSN fragments,
            # tokens, SQL). Callers get a stable code; details stay in logs.
            logger.warning("connector test failed",
                           connector=str(connection.connector_id))
            code = getattr(exc, "code", "CONNECTION_FAILED")
            return {"ok": False, "error": "Connection test failed",
                    "code": str(code)[:64]}

    # -- audit / security events ------------------------------------------------------
    async def _audit(self, org_id: UUID, action: str, resource_type: str,
                     resource_id: UUID, meta: dict[str, Any]) -> None:
        try:
            from openagent.db.models.audit_log import AuditLog
            self.db.add(AuditLog(organization_id=org_id, actor_user_id=None,
                                 action=action, resource_type=resource_type,
                                 resource_id=resource_id, metadata=dict(meta or {})))
            await self.db.flush()
        except Exception as exc:
            logger.warning("connector audit skipped", error=str(exc))

    async def _security_event(self, org_id: UUID | None, user_id: UUID | None,
                              event_type: str, meta: dict[str, Any]) -> None:
        try:
            from openagent.db.models.security_event import SecurityEvent
            self.db.add(SecurityEvent(user_id=user_id, organization_id=org_id,
                                      event_type=event_type,
                                      metadata=dict(meta or {})))  # type: ignore[arg-type]
            await self.db.flush()
        except Exception as exc:
            logger.warning("connector security event skipped", error=str(exc))
