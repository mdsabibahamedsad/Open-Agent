"""Sandbox domain service: lifecycle, policy-gated execution, leases, artifacts.

Tenant-scoped manager. Every execution flows::

    validate -> authorize (caller) -> profile resolve -> command policy ->
    workdir jail -> network gate -> risk score -> approval hook (MP19) ->
    quota -> provider -> redact -> artifacts -> audit/events/metrics

Secrets are ref-only: ``credential_ref`` handles resolve server-side into
short-lived env values that are redacted from every persisted surface and
dropped after execution.
"""

from __future__ import annotations

import asyncio
import io
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.code.security import redact_dict, redact_text
from openagent.db.models.audit_log import AuditLog
from openagent.db.models.sandbox import (
    Sandbox,
    SandboxArtifact,
    SandboxEvent,
    SandboxExecution,
    SandboxExecutionStatus,
    SandboxImagePolicy,
    SandboxLease,
    SandboxProfileRow,
    SandboxProvider as SandboxProviderEnum,
    SandboxStatus,
)
from openagent.sandbox import security as sec
from openagent.sandbox.config import SandboxSettings, is_production, load_settings
from openagent.sandbox.profiles import (
    SandboxProfile,
    get_profile,
    profile_from_dict,
    profile_to_dict,
)
from openagent.sandbox.providers import (
    ContainerSpec,
    ExecutionSpec,
    SandboxError,
    SandboxProvider,
    create_provider,
)

logger = structlog.get_logger("sandbox.service")

__all__ = [
    "SandboxSecurityError", "SandboxPolicyDenied", "SandboxNotFound",
    "SandboxManager",
]


class SandboxSecurityError(Exception):
    pass


class SandboxPolicyDenied(SandboxSecurityError):
    pass


class SandboxNotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _eid(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}_{uuid.uuid4().hex[:8]}"


def _st(status: Any) -> str:
    """Normalize a status enum-or-string to its value (driver-safe)."""
    return str(getattr(status, "value", status))


_SANDBOX_EVENT_METRICS = {
    "sandbox.created": "sandbox_created_total",
    "sandbox.destroyed": "sandbox_destroyed_total",
    "sandbox.execution.requested": "sandbox_execution_total",
    "sandbox.execution.allowed": "sandbox_execution_allowed_total",
    "sandbox.execution.denied": "sandbox_policy_denied",
    "sandbox.execution.completed": "sandbox_execution_completed_total",
    "sandbox.network.denied": "sandbox_policy_denied",
    "sandbox.credential.injected": "sandbox_credential_injections_total",
    "sandbox.credential.revoked": "sandbox_credential_revocations_total",
    "sandbox.artifact.created": "sandbox_artifacts_total",
    "sandbox.approval.required": "sandbox_approval_required_total",
    "sandbox.resource_limit": "sandbox_resource_limit",
}


def _record_metric(etype: str, payload: Optional[dict] = None) -> None:
    try:
        from openagent.core.metrics import metrics as _metrics
    except Exception:
        return
    try:
        name = _SANDBOX_EVENT_METRICS.get(etype)
        if name is None:
            return
        labels: dict[str, str] = {}
        for key in ("status", "profile", "risk_level"):
            val = (payload or {}).get(key)
            if isinstance(val, str) and val:
                labels[key] = val
        _metrics.counter(name, 1.0, labels or None,
                         help_text=f"OpenAgent sandbox metric {name}")
        status = (payload or {}).get("status")
        if etype == "sandbox.execution.completed" and status == "TIMED_OUT":
            _metrics.counter("sandbox_timeout_total", 1.0, None,
                             help_text="OpenAgent sandbox metric sandbox_timeout_total")
        if etype == "sandbox.execution.completed" and (payload or {}).get("oom_killed"):
            _metrics.counter("sandbox_oom_total", 1.0, None,
                             help_text="OpenAgent sandbox metric sandbox_oom_total")
        if status in ("FAILED", "SANDBOX_ERROR"):
            _metrics.counter("sandbox_execution_failure", 1.0, labels or None,
                             help_text="OpenAgent sandbox metric sandbox_execution_failure")
        if status == "SUCCEEDED":
            _metrics.counter("sandbox_execution_success", 1.0, labels or None,
                             help_text="OpenAgent sandbox metric sandbox_execution_success")
    except Exception:
        logger.warning("sandbox_metrics_skipped", event=etype)


class SandboxManager:
    """Tenant-scoped sandbox orchestration."""

    def __init__(self, db: AsyncSession,
                 credential_resolver: Any = None,
                 storage: Any = None,
                 settings: Optional[SandboxSettings] = None,
                 provider: Optional[SandboxProvider] = None):
        self.db = db
        self._credential_resolver = credential_resolver
        self._storage = storage
        self._settings = settings
        self._provider = provider
        self._runs: dict[str, asyncio.Task] = {}

    # -- internal helpers -------------------------------------------------
    def _settings_obj(self) -> SandboxSettings:
        if self._settings is None:
            self._settings = load_settings()
        return self._settings

    def _provider_obj(self) -> SandboxProvider:
        if self._provider is not None:
            return self._provider
        s = self._settings_obj()
        if s.provider == "local":
            if is_production() or not s.allow_local_fallback:
                raise SandboxPolicyDenied(
                    "Local execution fallback is not permitted here "
                    "(production or SANDBOX_ALLOW_LOCAL_FALLBACK=false)")
            logger.warning("sandbox_local_fallback",
                           detail="NOT a security boundary; dev-only")
            self._provider = create_provider(
                "local", root=s.workspace_root)
            return self._provider
        if s.provider == "docker":
            self._provider = create_provider("docker")
            return self._provider
        raise SandboxPolicyDenied(f"Sandbox provider '{s.provider}' unavailable")

    async def _emit(self, organization_id: UUID, etype: str, *,
                    sandbox_id: Optional[UUID] = None,
                    execution_id: Optional[UUID] = None,
                    payload: Optional[dict] = None) -> SandboxEvent:
        ev = SandboxEvent(
            event_id=_eid("sbx"), type=etype, organization_id=organization_id,
            sandbox_id=sandbox_id, execution_id=execution_id,
            payload=redact_dict(payload or {}), meta={}, )
        self.db.add(ev)
        await self.db.flush()
        _record_metric(etype, ev.payload)
        return ev

    async def _audit(self, organization_id: UUID, actor: Optional[UUID], action: str,
                     resource: str, resource_id: Optional[UUID],
                     meta: Optional[dict] = None) -> None:
        self.db.add(AuditLog(
            organization_id=organization_id, actor_user_id=actor, action=action,
            resource_type=resource, resource_id=resource_id,
            metadata=redact_dict(meta or {})))
        await self.db.flush()

    def _storage_service(self) -> Any:
        if self._storage is not None:
            return self._storage
        try:
            from openagent.core.storage import create_storage_service
            self._storage = create_storage_service()
            return self._storage
        except Exception:
            return None

    async def _get_sandbox(self, sandbox_id: UUID, organization_id: UUID) -> Sandbox:
        sb = await self.db.scalar(select(Sandbox).where(
            Sandbox.id == sandbox_id, Sandbox.organization_id == organization_id))
        if sb is None:
            raise SandboxNotFound("Sandbox not found")
        return sb

    async def _get_execution(self, execution_id: UUID,
                             organization_id: UUID) -> SandboxExecution:
        ex = await self.db.scalar(select(SandboxExecution).where(
            SandboxExecution.id == execution_id,
            SandboxExecution.organization_id == organization_id))
        if ex is None:
            raise SandboxNotFound("Execution not found")
        return ex

    # -- profiles ------------------------------------------------------------
    async def resolve_profile(self, name: str,
                              organization_id: Optional[UUID] = None) -> SandboxProfile:
        """Builtin profile overlaid with org customizations (validated)."""
        base = get_profile(name)
        if organization_id is not None:
            row = await self.db.scalar(select(SandboxProfileRow).where(
                SandboxProfileRow.organization_id == organization_id,
                SandboxProfileRow.profile_id == base.name.upper()))
            if row is not None:
                merged = dict(profile_to_dict(base))
                custom = dict(row.config or {})
                # Shallow overlay; nested policy blocks replace wholesale.
                merged.update({k: v for k, v in custom.items() if k in merged})
                custom_profile = profile_from_dict(merged)
                custom_profile.assert_valid()
                return custom_profile
        return base

    def _clamp_profile(self, profile: SandboxProfile) -> SandboxProfile:
        """Fail closed when a profile exceeds server caps (§30-§32)."""
        s = self._settings_obj()
        violations: list[str] = []
        if profile.cpu > s.max_cpu:
            violations.append(f"cpu {profile.cpu} > server max {s.max_cpu}")
        if profile.memory_mb > s.max_memory_mb:
            violations.append(f"memory {profile.memory_mb}MB > server max {s.max_memory_mb}MB")
        if profile.disk_mb > s.max_disk_mb:
            violations.append(f"disk {profile.disk_mb}MB > server max {s.max_disk_mb}MB")
        if profile.pids_limit > s.max_pids:
            violations.append(f"pids {profile.pids_limit} > server max {s.max_pids}")
        if profile.timeout_seconds > s.max_timeout:
            violations.append(f"timeout {profile.timeout_seconds}s > server max {s.max_timeout}s")
        if violations:
            raise SandboxPolicyDenied("Profile exceeds server caps: " + "; ".join(violations))
        return profile

    async def list_profiles(self, organization_id: UUID) -> list[dict[str, Any]]:
        out = []
        for builtin in ("READ_ONLY", "TEST", "LINT", "TYPECHECK", "BUILD",
                        "PACKAGE", "DEVELOPMENT", "DATA_PROCESSING", "CUSTOM"):
            out.append(profile_to_dict(await self.resolve_profile(builtin, organization_id)))
        return out

    async def upsert_profile(self, organization_id: UUID, config: dict[str, Any],
                             actor: Optional[UUID] = None) -> dict[str, Any]:
        from openagent.sandbox.profiles import validate_profile_dict
        problems = validate_profile_dict(config)
        if problems:
            raise SandboxSecurityError("Invalid profile: " + "; ".join(problems))
        name = str(config.get("name", "CUSTOM")).upper()
        if name not in ("READ_ONLY", "TEST", "LINT", "TYPECHECK", "BUILD",
                        "PACKAGE", "DEVELOPMENT", "DATA_PROCESSING", "CUSTOM"):
            raise SandboxSecurityError(f"Unknown profile '{name}'")
        row = await self.db.scalar(select(SandboxProfileRow).where(
            SandboxProfileRow.organization_id == organization_id,
            SandboxProfileRow.profile_id == name))
        if row is None:
            row = SandboxProfileRow(
                profile_id=name, organization_id=organization_id,
                name=name, config=config, is_default=False, meta={})
            self.db.add(row)
        else:
            row.config = config
        await self._audit(organization_id, actor, "sandbox.profile.upserted",
                          "sandbox_profile", row.id, {"profile": name})
        await self.db.commit()
        await self.db.refresh(row)
        return {"profile_id": row.profile_id, "config": row.config}

    async def delete_profile(self, organization_id: UUID, name: str,
                             actor: Optional[UUID] = None) -> None:
        row = await self.db.scalar(select(SandboxProfileRow).where(
            SandboxProfileRow.organization_id == organization_id,
            SandboxProfileRow.profile_id == name.upper()))
        if row is None:
            raise SandboxNotFound("Profile customization not found")
        await self.db.delete(row)
        await self._audit(organization_id, actor, "sandbox.profile.deleted",
                          "sandbox_profile", row.id, {"profile": name})
        await self.db.commit()

    # -- images ---------------------------------------------------------------
    async def check_image(self, image: str, digest: str, trust: str,
                          organization_id: Optional[UUID] = None) -> dict[str, Any]:
        """Image trust gate (§15-§17). Production requires pinned digests."""
        s = self._settings_obj()
        tier = (trust or "CUSTOM").upper()
        if organization_id is not None:
            pol = await self.db.scalar(select(SandboxImagePolicy).where(
                SandboxImagePolicy.organization_id == organization_id,
                SandboxImagePolicy.image == image))
            if pol is not None:
                if not pol.allowed:
                    raise SandboxPolicyDenied(f"Image '{image}' denied by organization policy")
                tier = str(pol.trust_tier.value if hasattr(pol.trust_tier, "value")
                           else pol.trust_tier)
                if pol.require_digest and not digest:
                    raise SandboxPolicyDenied(
                        f"Image '{image}' requires a pinned digest")
        if tier == "UNTRUSTED":
            raise SandboxPolicyDenied("UNTRUSTED images require LEVEL_4 + explicit policy")
        if is_production() and not digest:
            raise SandboxPolicyDenied("Production execution requires a pinned image digest")
        _ = s
        return {"image": image, "digest": digest, "trust_tier": tier,
                "pinned": bool(digest)}

    # -- sandboxes --------------------------------------------------------------
    async def create_sandbox(self, *, organization_id: UUID, profile: str = "TEST",
                             owner_id: Optional[UUID] = None,
                             task_id: Optional[UUID] = None,
                             workspace_host_path: Optional[str] = None,
                             workspace_mode: str = "WORKSPACE_RW",
                             image: Optional[str] = None,
                             image_digest: Optional[str] = None,
                             ttl_seconds: int = 3600,
                             labels: Optional[dict[str, str]] = None) -> Sandbox:
        s = self._settings_obj()
        prof = self._clamp_profile(await self.resolve_profile(profile, organization_id))
        active = await self.db.scalar(select(func.count()).select_from(Sandbox).where(
            Sandbox.organization_id == organization_id,
            Sandbox.status.notin_([SandboxStatus.DESTROYED, SandboxStatus.EXPIRED])))
        if (active or 0) >= s.max_sandboxes_per_org:
            raise SandboxPolicyDenied("Organization sandbox quota exceeded")
        img = image or s.image or "openagent-sandbox-base"
        img_digest = image_digest if image_digest is not None else s.image_digest
        await self.check_image(img, img_digest, prof.image_trust or "CORE", organization_id)
        if img_digest:
            img_digest = img_digest if img_digest.startswith("sha256:") else img_digest
        mounts: list[dict[str, Any]] = []
        if workspace_host_path:
            mounts = await self._workspace_mount(organization_id, workspace_host_path,
                                                 workspace_mode, prof)
        provider = self._provider_obj()
        network_mode = prof.network.mode
        container_network = "NO_NETWORK"
        if network_mode != "NO_NETWORK":
            if not s.egress_proxy:
                raise SandboxPolicyDenied(
                    f"Network mode {network_mode} requires a deployment egress filter "
                    "(SANDBOX_EGRESS_PROXY); failing closed")
            container_network = "BRIDGED"
        env = sec.build_container_env(prof.environment)
        if container_network != "NO_NETWORK" and s.egress_proxy:
            env = {**env, "HTTP_PROXY": s.egress_proxy, "HTTPS_PROXY": s.egress_proxy,
                   "http_proxy": s.egress_proxy, "https_proxy": s.egress_proxy}
        sb = Sandbox(
            sandbox_id=_eid("sbx"), organization_id=organization_id,
            owner_id=owner_id, task_id=task_id, profile=prof.name,
            provider=(SandboxProviderEnum.docker if getattr(provider, "provider_name",
                                                             "docker") == "docker"
                      else SandboxProviderEnum.local),
            status=SandboxStatus.CREATING, image=img, image_digest=img_digest,
            expires_at=_now() + timedelta(seconds=max(60, ttl_seconds)),
            resource_config={"cpu": prof.cpu, "memory_mb": prof.memory_mb,
                             "disk_mb": prof.disk_mb, "pids_limit": prof.pids_limit,
                             "timeout_seconds": prof.timeout_seconds},
            mounts=mounts, meta={"labels": labels or {}})
        self.db.add(sb)
        await self.db.flush()
        spec = ContainerSpec(
            image=img, image_digest=img_digest, cpu=prof.cpu,
            memory_mb=prof.memory_mb, disk_mb=prof.disk_mb,
            pids_limit=prof.pids_limit, readonly_rootfs=prof.readonly_rootfs,
            network_mode=container_network, mounts=mounts, env=env,
            labels={"openagent.sandbox": sb.sandbox_id,
                    "openagent.org": str(organization_id),
                    **(labels or {})})
        try:
            handle = await provider.create(spec)
        except SandboxError as e:
            sb.status = SandboxStatus.FAILED
            await self._emit(organization_id, "sandbox.execution.denied",
                             sandbox_id=sb.id, payload={"reason": str(e)[:300]})
            await self.db.commit()
            raise
        sb.provider_handle = handle
        sb.status = SandboxStatus.CREATED
        await self._emit(organization_id, "sandbox.created", sandbox_id=sb.id,
                         payload={"profile": prof.name, "provider": sb.provider.value
                                  if hasattr(sb.provider, "value") else str(sb.provider),
                                  "image": img, "pinned": bool(img_digest)})
        await self._audit(organization_id, owner_id, "sandbox.created", "sandbox",
                          sb.id, {"profile": prof.name, "image": img})
        await self.db.commit()
        await self.db.refresh(sb)
        return sb

    async def _workspace_mount(self, organization_id: UUID, host_path: str,
                               mode: str, prof: SandboxProfile) -> list[dict[str, Any]]:
        """Explicit controlled workspace mount (§19): tenant root, no traversal,
        no symlinks out, ownership assumed validated by the caller (workspace
        was org-checked before its server-side path was handed over)."""
        s = self._settings_obj()
        if prof.filesystem.mode == "ISOLATED":
            raise SandboxPolicyDenied("Profile filesystem is ISOLATED; workspace mount denied")
        if mode not in ("WORKSPACE_RW", "WORKSPACE_RO"):
            raise SandboxPolicyDenied(f"Unknown workspace mount mode '{mode}'")
        if prof.filesystem.mode == "WORKSPACE_RO" and mode == "WORKSPACE_RW":
            raise SandboxPolicyDenied("Profile allows read-only workspace mounts only")
        root = Path(s.workspace_root).resolve()
        candidate = Path(host_path)
        if not candidate.is_absolute():
            candidate = (root / host_path)
        try:
            real = candidate.resolve()
            real.relative_to(root)
        except ValueError:
            raise SandboxSecurityError("Workspace mount escapes the tenant workspace root")
        except OSError as e:
            raise SandboxSecurityError(f"Workspace mount stat failed: {e}")
        if not real.exists():
            raise SandboxNotFound("Workspace path does not exist")
        if real.is_symlink():
            raise SandboxSecurityError("Workspace mount may not be a bare symlink")
        read_only = (mode == "WORKSPACE_RO")
        check = sec.validate_mount(str(real), prof.filesystem.workspace or "/workspace",
                                   read_only)
        if not check.valid:
            raise SandboxSecurityError(f"Refusing workspace mount: {check.reason}")
        _ = organization_id
        return [{"host": str(real),
                 "container": prof.filesystem.workspace or "/workspace",
                 "read_only": read_only}]

    async def list_sandboxes(self, organization_id: UUID,
                             status: Optional[str] = None) -> list[Sandbox]:
        q = select(Sandbox).where(Sandbox.organization_id == organization_id)
        if status:
            q = q.where(Sandbox.status == status)
        res = await self.db.execute(q.order_by(Sandbox.created_at.desc()).limit(100))
        return list(res.scalars().all())

    async def get_sandbox(self, sandbox_id: UUID, organization_id: UUID) -> Sandbox:
        return await self._get_sandbox(sandbox_id, organization_id)

    async def start_sandbox(self, sandbox_id: UUID, organization_id: UUID,
                            actor: Optional[UUID] = None) -> Sandbox:
        sb = await self._get_sandbox(sandbox_id, organization_id)
        if sb.status not in (SandboxStatus.CREATED, SandboxStatus.STOPPED) \
                and _st(sb.status) not in ("CREATED", "STOPPED"):
            raise SandboxPolicyDenied(f"Sandbox is {_st(sb.status)}; cannot start")
        if sb.expires_at and sb.expires_at <= _now():
            sb.status = SandboxStatus.EXPIRED
            await self.db.commit()
            raise SandboxPolicyDenied("Sandbox lease expired")
        sb.status = SandboxStatus.STARTING
        await self.db.flush()
        try:
            await self._provider_obj().start(sb.provider_handle or "")
        except SandboxError as e:
            sb.status = SandboxStatus.FAILED
            await self.db.commit()
            raise SandboxSecurityError(f"Sandbox start failed: {e}")
        sb.status = SandboxStatus.READY
        sb.started_at = _now()
        await self._audit(organization_id, actor, "sandbox.started", "sandbox", sb.id, {})
        await self.db.commit()
        await self.db.refresh(sb)
        return sb

    async def stop_sandbox(self, sandbox_id: UUID, organization_id: UUID,
                           actor: Optional[UUID] = None) -> Sandbox:
        sb = await self._get_sandbox(sandbox_id, organization_id)
        if sb.status in (SandboxStatus.DESTROYED, SandboxStatus.DESTROYING) \
                or _st(sb.status) in ("DESTROYED", "DESTROYING"):
            return sb
        sb.status = SandboxStatus.STOPPING
        await self.db.flush()
        try:
            if sb.provider_handle:
                await self._provider_obj().stop(sb.provider_handle)
        except SandboxError as e:
            logger.warning("sandbox_stop_failed", sandbox=str(sb.id), error=str(e)[:200])
        for task in [t for eid, t in self._runs.items()]:
            task.cancel()
        sb.status = SandboxStatus.STOPPED
        await self._audit(organization_id, actor, "sandbox.stopped", "sandbox", sb.id, {})
        await self.db.commit()
        await self.db.refresh(sb)
        return sb

    async def destroy_sandbox(self, sandbox_id: UUID, organization_id: UUID,
                              actor: Optional[UUID] = None) -> None:
        sb = await self._get_sandbox(sandbox_id, organization_id)
        sb.status = SandboxStatus.DESTROYING
        await self.db.flush()
        try:
            if sb.provider_handle:
                try:
                    await self._provider_obj().stop(sb.provider_handle)
                except SandboxError:
                    pass
                await self._provider_obj().destroy(sb.provider_handle)
        except SandboxError as e:
            logger.warning("sandbox_destroy_failed", sandbox=str(sb.id), error=str(e)[:200])
        for task in [t for eid, t in self._runs.items()]:
            task.cancel()
        # Release leases; temporary credentials were never persisted.
        leases = (await self.db.execute(select(SandboxLease).where(
            SandboxLease.sandbox_id == sb.id,
            SandboxLease.released_at.is_(None)))).scalars().all()
        for lease in leases:
            lease.released_at = _now()
        sb.status = SandboxStatus.DESTROYED
        sb.destroyed_at = _now()
        await self._emit(organization_id, "sandbox.destroyed", sandbox_id=sb.id,
                         payload={"provider_handle_set": bool(sb.provider_handle)})
        await self._audit(organization_id, actor, "sandbox.destroyed", "sandbox", sb.id, {})
        await self.db.commit()

    # -- execution ---------------------------------------------------------------
    async def _check_quota(self, organization_id: UUID) -> None:
        s = self._settings_obj()
        running = await self.db.scalar(select(func.count()).select_from(
            SandboxExecution).where(
                SandboxExecution.organization_id == organization_id,
                SandboxExecution.status.in_([SandboxExecutionStatus.QUEUED,
                                             SandboxExecutionStatus.RUNNING])))
        if (running or 0) >= s.max_concurrent_executions_per_org:
            raise SandboxPolicyDenied("Organization concurrent-execution quota exceeded")

    async def _check_lease(self, sb: Sandbox, owner: Optional[str]) -> None:
        """Default: one task, one sandbox. Shared access needs an explicit lease."""
        now = _now()
        leases = (await self.db.execute(select(SandboxLease).where(
            SandboxLease.sandbox_id == sb.id,
            SandboxLease.released_at.is_(None),
            SandboxLease.expires_at > now))).scalars().all()
        if not leases:
            return
        if owner and any(l.owner == owner for l in leases):
            return
        raise SandboxPolicyDenied(
            "Sandbox is leased by another owner; acquire a lease for shared access")

    async def execute(self, *, sandbox_id: UUID, organization_id: UUID,
                      command: str, workdir: str = "/workspace",
                      env: Optional[dict[str, str]] = None,
                      credential_refs: Optional[dict[str, str]] = None,
                      task_id: Optional[UUID] = None,
                      actor: Optional[UUID] = None,
                      owner: Optional[str] = None,
                      timeout_seconds: Optional[int] = None,
                      approved: bool = False,
                      approval_id: Optional[UUID] = None,
                      artifacts: Optional[list[dict[str, str]]] = None,
                      target_environment: str = "sandbox") -> dict[str, Any]:
        """Policy-gated execution. Returns the normalized result (§8)."""
        s = self._settings_obj()
        sb = await self._get_sandbox(sandbox_id, organization_id)
        if sb.status not in (SandboxStatus.READY, SandboxStatus.RUNNING) \
                and _st(sb.status) not in ("READY", "RUNNING"):
            raise SandboxPolicyDenied(
                f"Sandbox is {_st(sb.status)}; start it before executing")
        if sb.expires_at and sb.expires_at <= _now():
            sb.status = SandboxStatus.EXPIRED
            await self.db.commit()
            raise SandboxPolicyDenied("Sandbox expired")
        await self._check_lease(sb, owner)
        await self._check_quota(organization_id)
        prof = self._clamp_profile(await self.resolve_profile(sb.profile, organization_id))

        # 1. command policy (structured argv; shell only with explicit grant)
        try:
            argv = sec.parse_argv(command, allow_shell=prof.commands.allow_shell)
        except ValueError as e:
            return await self._denied(
                organization_id, sb, task_id, actor, command, prof, str(e))
        allowed, reason, category = sec.check_command(command, prof.commands)
        if not allowed:
            return await self._denied(
                organization_id, sb, task_id, actor, command, prof, reason,
                category=category)

        # 2. workdir jail (inside the mounted workspace or /tmp)
        workdir_check = self._check_workdir(sb, workdir, prof)
        if not workdir_check[0]:
            return await self._denied(
                organization_id, sb, task_id, actor, command, prof, workdir_check[1],
                category=category)

        # 3. network gate: non-NONE modes require deployment egress filtering
        if prof.network.mode != "NO_NETWORK" and not s.egress_proxy:
            return await self._denied(
                organization_id, sb, task_id, actor, command, prof,
                f"Network mode {prof.network.mode} unavailable (no egress filter); failing closed",
                category=category, event="sandbox.network.denied")

        # 4. risk score (server-side; the LLM never assigns trust)
        try:
            resolved_creds = await self._resolve_credentials(credential_refs or {})
        except SandboxPolicyDenied as e:
            return await self._denied(
                organization_id, sb, task_id, actor, command, prof, str(e),
                category=category)
        decision = sec.score_execution_risk(
            category=category, network_mode=prof.network.mode,
            filesystem_mode=prof.filesystem.mode,
            has_credentials=bool(resolved_creds), command=command,
            target_environment=target_environment)
        if target_environment.lower() in ("production", "prod"):
            return await self._denied(
                organization_id, sb, task_id, actor, command, prof,
                "Production targets require explicit configuration + approval",
                category=category)

        timeout = min(timeout_seconds or prof.timeout_seconds, s.max_timeout)
        timeout = max(5, timeout)

        await self._emit(organization_id, "sandbox.execution.requested",
                         sandbox_id=sb.id,
                         payload={"profile": prof.name, "command": command[:300],
                                  "category": category, "risk_level": decision.risk_level})
        await self._audit(organization_id, actor, "sandbox.execution.requested",
                          "sandbox", sb.id,
                          {"profile": prof.name, "command": redact_text(command)[:300]})

        # 5. approval hook (MP19 owns the decision; the WAITING state is the contract).
        # A client boolean is never proof of approval: execution requires a
        # persisted, human-granted approval bound to this exact command.
        verified = False
        if approval_id is not None:
            from openagent.approvals.integrations import consume_approval
            ok, _ = await consume_approval(
                self.db, approval_id=approval_id, organization_id=organization_id,
                action_type="sandbox.execute", action_category="SANDBOX_EXECUTION",
                target_type="sandbox", target_id=str(sb.id),
                params={"command": command, "workdir": workdir,
                        "profile": prof.name},
                environment=target_environment)
            verified = ok
        if decision.required_approval and not verified:
            from openagent.approvals.integrations import park_for_approval
            parked = await park_for_approval(
                self.db, organization_id=organization_id,
                action_type="sandbox.execute", action_category="SANDBOX_EXECUTION",
                target_type="sandbox", target_id=str(sb.id),
                params={"command": command, "workdir": workdir,
                        "profile": prof.name},
                environment=target_environment,
                impact_summary=f"Sandbox execution [{category}] risk={decision.risk_level}",
                requester_type="agent",
                task_id=str(task_id) if task_id else None)
            ex = SandboxExecution(
                execution_id=_eid("exe"), organization_id=organization_id,
                sandbox_id=sb.id, task_id=task_id, command=redact_text(command)[:2000],
                workdir=workdir, profile=prof.name,
                status=SandboxExecutionStatus.WAITING,
                risk_level=decision.risk_level, risk_reasons=decision.risk_reasons,
                policy_decision={"allowed": False, "requires_approval": True,
                                 "category": category, "reasons": decision.risk_reasons,
                                 "approval_id": str(parked.id) if parked else None},
                started_at=_now())
            self.db.add(ex)
            await self.db.flush()
            await self._emit(organization_id, "sandbox.approval.required",
                             sandbox_id=sb.id, execution_id=ex.id,
                             payload={"risk_level": decision.risk_level,
                                      "reasons": decision.risk_reasons,
                                      "approval_id": str(parked.id) if parked else None})
            await self.db.commit()
            await self.db.refresh(ex)
            return {"execution_id": str(ex.id), "status": "WAITING_FOR_APPROVAL",
                    "approval_id": str(parked.id) if parked else None,
                    "risk_level": decision.risk_level,
                    "risk_reasons": decision.risk_reasons,
                    "message": "Execution parked for human approval"}

        # 6. build the container env (ref-only credentials, never logged)
        try:
            env_policy = prof.environment
            if credential_refs:
                env_policy = sec.EnvironmentPolicy(
                    action=env_policy.action, allowed_names=env_policy.allowed_names,
                    values={**(env_policy.values or {}), **(env or {})},
                    credential_refs=dict(credential_refs))
            elif env:
                env_policy = sec.EnvironmentPolicy(
                    action=env_policy.action, allowed_names=env_policy.allowed_names,
                    values={**(env_policy.values or {}), **env},
                    credential_refs=dict(env_policy.credential_refs))
            container_env = sec.build_container_env(
                env_policy, host_env=None, resolved_credentials=resolved_creds)
        except ValueError as e:
            return await self._denied(
                organization_id, sb, task_id, actor, command, prof, str(e),
                category=category)
        if resolved_creds:
            await self._emit(organization_id, "sandbox.credential.injected",
                             sandbox_id=sb.id,
                             payload={"count": len(resolved_creds),
                                      "refs": sorted(credential_refs or {})})

        ex = SandboxExecution(
            execution_id=_eid("exe"), organization_id=organization_id,
            sandbox_id=sb.id, task_id=task_id, command=redact_text(command)[:2000],
            workdir=workdir, profile=prof.name, status=SandboxExecutionStatus.RUNNING,
            risk_level=decision.risk_level, risk_reasons=decision.risk_reasons,
            policy_decision={"allowed": True, "category": category,
                             "network": prof.network.mode,
                             "filesystem": prof.filesystem.mode,
                             "reasons": decision.risk_reasons},
            started_at=_now())
        self.db.add(ex)
        await self.db.flush()
        await self._emit(organization_id, "sandbox.execution.allowed",
                         sandbox_id=sb.id, execution_id=ex.id,
                         payload={"profile": prof.name, "risk_level": decision.risk_level})
        sb.status = SandboxStatus.RUNNING
        await self.db.flush()
        await self.db.commit()

        # 7. run through the provider with cancellation support
        provider = self._provider_obj()
        spec = ExecutionSpec(argv=argv, workdir=workdir, env=container_env,
                             timeout_seconds=timeout,
                             max_output_bytes=prof.max_output_bytes)
        exec_task = asyncio.ensure_future(
            provider.execute(sb.provider_handle or "", spec))
        self._runs[str(ex.id)] = exec_task
        outcome = None
        cancelled = False
        try:
            outcome = await exec_task
        except asyncio.CancelledError:
            cancelled = True
            try:
                await provider.stop(sb.provider_handle or "")
            except SandboxError:
                pass
        finally:
            self._runs.pop(str(ex.id), None)

        # 8. normalize, redact, persist (output via storage refs, never raw secrets)
        # NOTE: resolved_creds held short-lived secrets; drop the reference now
        # so only redacted tails + storage refs persist past this point.
        del resolved_creds
        if cancelled:
            return await self._finalize(
                organization_id, sb, ex, actor, "CANCELLED", None, "", "",
                0, False, False, None, prof, [])
        status = "SUCCEEDED" if outcome.exit_code == 0 else "FAILED"
        if outcome.timed_out:
            status = "TIMED_OUT"
            await self._emit(organization_id, "sandbox.resource_limit",
                             sandbox_id=sb.id, execution_id=ex.id,
                             payload={"kind": "timeout", "timeout_seconds": timeout})
        if outcome.oom_killed:
            status = "RESOURCE_LIMIT"
            await self._emit(organization_id, "sandbox.resource_limit",
                             sandbox_id=sb.id, execution_id=ex.id,
                             payload={"kind": "oom", "peak_memory_mb": outcome.peak_memory_mb})
        stdout_ref = await self._store_text(organization_id, ex, "stdout", outcome.stdout)
        stderr_ref = await self._store_text(organization_id, ex, "stderr", outcome.stderr)
        artifact_refs = await self._collect_artifacts(
            organization_id, sb, ex, prof, artifacts or [])
        return await self._finalize(
            organization_id, sb, ex, actor, status, outcome.exit_code,
            outcome.stdout, outcome.stderr, outcome.duration_ms, outcome.timed_out,
            outcome.oom_killed, outcome.peak_memory_mb, prof,
            artifact_refs, stdout_ref=stdout_ref, stderr_ref=stderr_ref,
            truncated=outcome.truncated)

    def _check_workdir(self, sb: Sandbox, workdir: str,
                       prof: SandboxProfile) -> tuple[bool, str]:
        wd = (workdir or "/workspace").strip()
        if wd in ("/tmp",) or wd.startswith("/tmp/"):
            if not prof.filesystem.allow_tmp_write:
                return False, "/tmp writes are disabled by profile"
            return True, "allowed"
        mounts = sb.mounts or []
        container_roots = [m.get("container", "/workspace") for m in mounts]
        if prof.filesystem.workspace and prof.filesystem.workspace not in container_roots:
            container_roots.append(prof.filesystem.workspace)
        for root in container_roots:
            if wd == root or wd.startswith(root.rstrip("/") + "/"):
                if ".." in wd.split("/"):
                    return False, "workdir traversal is not allowed"
                return True, "allowed"
        return False, f"workdir '{wd}' is outside the mounted workspace"

    async def _denied(self, organization_id: UUID, sb: Sandbox,
                      task_id: Optional[UUID], actor: Optional[UUID],
                      command: str, prof: SandboxProfile, reason: str,
                      category: str = "system",
                      event: str = "sandbox.execution.denied") -> dict[str, Any]:
        ex = SandboxExecution(
            execution_id=_eid("exe"), organization_id=organization_id,
            sandbox_id=sb.id, task_id=task_id, command=redact_text(command)[:2000],
            workdir="/workspace", profile=prof.name,
            status=SandboxExecutionStatus.POLICY_DENIED,
            risk_level="HIGH", risk_reasons=[reason],
            policy_decision={"allowed": False, "category": category, "reason": reason},
            started_at=_now(), completed_at=_now())
        self.db.add(ex)
        await self.db.flush()
        await self._emit(organization_id, event, sandbox_id=sb.id, execution_id=ex.id,
                         payload={"reason": reason[:300], "profile": prof.name})
        await self._audit(organization_id, actor, event, "sandbox", sb.id,
                          {"reason": reason[:300]})
        await self.db.commit()
        await self.db.refresh(ex)
        return {"execution_id": str(ex.id), "status": "POLICY_DENIED",
                "reason": reason, "risk_level": "HIGH"}

    async def _resolve_credentials(self, refs: dict[str, str]) -> dict[str, str]:
        """Resolve credential_ref handles server-side (never logged, never modeled).

        Resolution requires an injected, authorized ``credential_resolver``
        (same pattern as the Code Agent): the sandbox never decrypts the
        credential store itself and never accepts raw secrets over the API.
        """
        if not refs:
            return {}
        if self._credential_resolver is None:
            raise SandboxPolicyDenied(
                "Credential injection requires a configured credential resolver; "
                "raw secrets are never accepted")
        resolved: dict[str, str] = {}
        for ref in refs:
            try:
                value = await self._credential_resolver(ref)
            except Exception as e:
                raise SandboxPolicyDenied(
                    f"Credential '{ref}' failed authorization") from e
            if not value:
                raise SandboxPolicyDenied(f"Credential '{ref}' not found/authorized")
            resolved[ref] = str(value)
        return resolved

    async def _store_text(self, organization_id: UUID, ex: SandboxExecution,
                          name: str, text: str) -> Optional[str]:
        if not text:
            return None
        svc = self._storage_service()
        if svc is None:
            return None
        key = f"sandbox/{organization_id}/{ex.execution_id}/{name}.log"
        try:
            stored = await svc.upload(key, io.BytesIO(
                redact_text(text).encode("utf-8", "replace")),
                "text/plain", f"{name}.log",
                metadata={"organization_id": str(organization_id)})
            return stored.key
        except Exception:
            return None

    async def _collect_artifacts(self, organization_id: UUID, sb: Sandbox,
                                 ex: SandboxExecution, prof: SandboxProfile,
                                 wanted: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Copy explicit container paths out via `docker cp` -> storage.

        Only paths under the workspace/artifacts mount are eligible; container
        paths are never exposed to callers (storage refs only).
        """
        if not wanted or not prof.allow_artifact_upload:
            return []
        provider = self._provider_obj()
        if getattr(provider, "provider_name", "docker") != "docker" or not sb.provider_handle:
            return []
        svc = self._storage_service()
        if svc is None:
            return []
        import tempfile
        refs: list[dict[str, Any]] = []
        roots = [m.get("container", "/workspace") for m in (sb.mounts or [])]
        roots.append("/artifacts")
        max_bytes = prof.max_artifacts_mb * 1024 * 1024
        for item in wanted[:20]:
            cpath = str(item.get("path", ""))
            name = str(item.get("name") or cpath.rsplit("/", 1)[-1])[:255]
            if not cpath or ".." in cpath.split("/"):
                continue
            if not any(cpath == r or cpath.startswith(r.rstrip("/") + "/") for r in roots):
                continue
            try:
                with tempfile.TemporaryDirectory(prefix="sbx-art-") as tmp:
                    proc = await asyncio.create_subprocess_exec(
                        "docker", "cp", f"{sb.provider_handle}:{cpath}", tmp,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE)
                    try:
                        _, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                        except ProcessLookupError:
                            pass
                        continue
                    if proc.returncode != 0:
                        continue
                    base = Path(tmp) / cpath.rsplit("/", 1)[-1]
                    if not base.exists() or not base.is_file():
                        continue
                    if base.stat().st_size > max_bytes:
                        continue
                    data = base.read_bytes()
                    # Secret scan before persisting artifacts.
                    from openagent.code.security import scan_text_for_secrets
                    try:
                        if scan_text_for_secrets(
                                data[:100000].decode("utf-8", "replace"), name):
                            continue
                    except Exception:
                        pass
                    key = f"sandbox/{organization_id}/{ex.execution_id}/artifacts/{name}"
                    stored = await svc.upload(key, io.BytesIO(data),
                                              "application/octet-stream", name,
                                              metadata={"organization_id": str(organization_id)})
                    art = SandboxArtifact(
                        organization_id=organization_id, sandbox_id=sb.id,
                        execution_id=ex.id, name=name, kind="file",
                        storage_ref=stored.key, size_bytes=len(data),
                        expires_at=_now() + timedelta(
                            days=self._settings_obj().artifact_retention_days),
                        meta={})
                    self.db.add(art)
                    await self.db.flush()
                    refs.append({"name": name, "ref": stored.key, "size_bytes": len(data)})
                    await self._emit(organization_id, "sandbox.artifact.created",
                                     sandbox_id=sb.id, execution_id=ex.id,
                                     payload={"name": name, "size_bytes": len(data)})
            except (OSError, SandboxError):
                continue
        return refs

    async def _finalize(self, organization_id: UUID, sb: Sandbox, ex: SandboxExecution,
                        actor: Optional[UUID],
                        status: str, exit_code: Optional[int],
                        stdout: str, stderr: str, duration_ms: int,
                        timed_out: bool, oom_killed: bool,
                        peak_memory_mb: Optional[int], prof: SandboxProfile,
                        artifacts: list[dict[str, Any]],
                        stdout_ref: Optional[str] = None,
                        stderr_ref: Optional[str] = None,
                        truncated: bool = False) -> dict[str, Any]:
        ex.status = SandboxExecutionStatus(status)
        ex.exit_code = exit_code
        ex.duration_ms = duration_ms
        ex.timed_out = timed_out
        ex.oom_killed = oom_killed
        ex.peak_memory_mb = peak_memory_mb
        ex.stdout_tail = redact_text(stdout[-8000:]) if stdout else None
        ex.stdout_ref = stdout_ref
        ex.stderr_ref = stderr_ref
        ex.artifacts = artifacts
        ex.completed_at = _now()
        if _st(sb.status) == "RUNNING":
            sb.status = SandboxStatus.READY
        # Temporary credentials are dropped here: nothing credential-valued was
        # persisted (only refs + redacted tails).
        await self._emit(organization_id, "sandbox.execution.completed",
                         sandbox_id=sb.id, execution_id=ex.id,
                         payload={"status": status, "exit_code": exit_code,
                                  "duration_ms": duration_ms, "profile": prof.name,
                                  "risk_level": ex.risk_level,
                                  "oom_killed": oom_killed, "truncated": truncated})
        await self._emit(organization_id, "sandbox.credential.revoked",
                         sandbox_id=sb.id, execution_id=ex.id, payload={})
        await self._audit(organization_id, actor, "sandbox.execution.completed",
                          "sandbox_execution", ex.id,
                          {"status": status, "exit_code": exit_code})
        await self.db.commit()
        await self.db.refresh(ex)
        return {"execution_id": str(ex.id), "status": status,
                "exit_code": exit_code, "duration_ms": duration_ms,
                "timed_out": timed_out, "oom_killed": oom_killed,
                "peak_memory_mb": peak_memory_mb,
                "stdout": stdout, "stderr": stderr,
                "stdout_tail": ex.stdout_tail, "stdout_ref": stdout_ref,
                "stderr_ref": stderr_ref, "artifacts": artifacts,
                "risk_level": ex.risk_level, "truncated": truncated}

    # -- reads ------------------------------------------------------------------
    async def list_executions(self, sandbox_id: UUID, organization_id: UUID,
                              limit: int = 50) -> list[SandboxExecution]:
        sb = await self._get_sandbox(sandbox_id, organization_id)
        res = await self.db.execute(select(SandboxExecution).where(
            SandboxExecution.sandbox_id == sb.id).order_by(
                SandboxExecution.created_at.desc()).limit(min(limit, 200)))
        return list(res.scalars().all())

    async def get_execution(self, execution_id: UUID,
                            organization_id: UUID) -> SandboxExecution:
        return await self._get_execution(execution_id, organization_id)

    async def cancel_execution(self, execution_id: UUID, organization_id: UUID,
                               actor: Optional[UUID] = None) -> dict[str, Any]:
        ex = await self._get_execution(execution_id, organization_id)
        if ex.status in (SandboxExecutionStatus.SUCCEEDED, SandboxExecutionStatus.FAILED,
                         SandboxExecutionStatus.TIMED_OUT, SandboxExecutionStatus.CANCELLED,
                         SandboxExecutionStatus.KILLED):
            return {"execution_id": str(ex.id), "status": str(ex.status)}
        task = self._runs.pop(str(ex.id), None)
        if task is not None:
            task.cancel()
        sb = await self._get_sandbox(ex.sandbox_id, organization_id)
        try:
            if sb.provider_handle:
                await self._provider_obj().stop(sb.provider_handle)
                await self._provider_obj().start(sb.provider_handle)
        except SandboxError as e:
            logger.warning("sandbox_cancel_restart_failed", error=str(e)[:200])
        ex.status = SandboxExecutionStatus.CANCELLED
        ex.completed_at = _now()
        if _st(sb.status) == "RUNNING":
            sb.status = SandboxStatus.READY
        await self._audit(organization_id, actor, "sandbox.execution.cancelled",
                          "sandbox_execution", ex.id, {})
        await self.db.commit()
        return {"execution_id": str(ex.id), "status": "CANCELLED"}

    async def sandbox_events(self, sandbox_id: UUID, organization_id: UUID,
                             limit: int = 100) -> list[SandboxEvent]:
        sb = await self._get_sandbox(sandbox_id, organization_id)
        res = await self.db.execute(select(SandboxEvent).where(
            SandboxEvent.sandbox_id == sb.id).order_by(
                SandboxEvent.created_at.desc()).limit(min(limit, 500)))
        return list(res.scalars().all())

    async def sandbox_artifacts(self, sandbox_id: UUID,
                                organization_id: UUID) -> list[SandboxArtifact]:
        sb = await self._get_sandbox(sandbox_id, organization_id)
        res = await self.db.execute(select(SandboxArtifact).where(
            SandboxArtifact.sandbox_id == sb.id).order_by(
                SandboxArtifact.created_at.desc()).limit(200))
        return list(res.scalars().all())

    # -- leases -------------------------------------------------------------------
    async def acquire_lease(self, sandbox_id: UUID, organization_id: UUID,
                            owner: str, ttl_seconds: int = 600,
                            task_id: Optional[UUID] = None) -> SandboxLease:
        sb = await self._get_sandbox(sandbox_id, organization_id)
        now = _now()
        existing = (await self.db.execute(select(SandboxLease).where(
            SandboxLease.sandbox_id == sb.id,
            SandboxLease.released_at.is_(None),
            SandboxLease.expires_at > now))).scalars().all()
        if any(l.owner != owner for l in existing):
            raise SandboxPolicyDenied("Sandbox is leased by another owner")
        lease = SandboxLease(
            sandbox_id=sb.id, organization_id=organization_id, owner=owner,
            task_id=task_id, acquired_at=now,
            expires_at=now + timedelta(seconds=max(30, ttl_seconds)),
            last_heartbeat_at=now)
        self.db.add(lease)
        await self.db.commit()
        await self.db.refresh(lease)
        return lease

    async def heartbeat_lease(self, lease_id: UUID, organization_id: UUID,
                              owner: str) -> SandboxLease:
        lease = await self.db.scalar(select(SandboxLease).where(
            SandboxLease.id == lease_id,
            SandboxLease.organization_id == organization_id,
            SandboxLease.released_at.is_(None)))
        if lease is None or lease.owner != owner:
            raise SandboxNotFound("Lease not found")
        lease.last_heartbeat_at = _now()
        lease.expires_at = _now() + timedelta(seconds=600)
        await self.db.commit()
        await self.db.refresh(lease)
        return lease

    async def release_lease(self, lease_id: UUID, organization_id: UUID,
                            owner: str) -> None:
        lease = await self.db.scalar(select(SandboxLease).where(
            SandboxLease.id == lease_id,
            SandboxLease.organization_id == organization_id,
            SandboxLease.released_at.is_(None)))
        if lease is None or lease.owner != owner:
            raise SandboxNotFound("Lease not found")
        lease.released_at = _now()
        await self.db.commit()

    # -- maintenance ----------------------------------------------------------------
    async def sweep(self, retention_days: Optional[int] = None) -> dict[str, int]:
        """GC: expired sandboxes, stale leases, expired artifacts (§86-§87)."""
        s = self._settings_obj()
        retention = retention_days or s.artifact_retention_days
        now = _now()
        counts = {"sandboxes": 0, "leases": 0, "artifacts": 0, "executions": 0}
        expired = (await self.db.execute(select(Sandbox).where(
            Sandbox.status.notin_([SandboxStatus.DESTROYED]),
            Sandbox.expires_at.is_not(None),
            Sandbox.expires_at <= now))).scalars().all()
        for sb in expired:
            try:
                if sb.provider_handle:
                    try:
                        await self._provider_obj().stop(sb.provider_handle)
                    except SandboxError:
                        pass
                    await self._provider_obj().destroy(sb.provider_handle)
            except SandboxError:
                pass
            sb.status = SandboxStatus.EXPIRED
            counts["sandboxes"] += 1
        stale = (await self.db.execute(select(SandboxLease).where(
            SandboxLease.released_at.is_(None),
            SandboxLease.expires_at <= now))).scalars().all()
        for lease in stale:
            lease.released_at = now
            counts["leases"] += 1
        old_arts = (await self.db.execute(select(SandboxArtifact).where(
            SandboxArtifact.expires_at.is_not(None),
            SandboxArtifact.expires_at <= now))).scalars().all()
        svc = self._storage_service()
        for art in old_arts:
            try:
                if svc is not None:
                    await svc.delete(art.storage_ref)
            except Exception:
                pass
            await self.db.delete(art)
            counts["artifacts"] += 1
        cutoff = now - timedelta(days=retention)
        old_exec = (await self.db.execute(select(SandboxExecution).where(
            SandboxExecution.completed_at.is_not(None),
            SandboxExecution.completed_at <= cutoff,
            SandboxExecution.status.notin_([SandboxExecutionStatus.RUNNING,
                                            SandboxExecutionStatus.QUEUED])))).scalars().all()
        for ex in old_exec[:1000]:
            await self.db.delete(ex)
            counts["executions"] += 1
        await self.db.commit()
        logger.info("sandbox.sweep", **counts)
        return counts
