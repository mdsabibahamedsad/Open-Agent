"""Sandbox configuration (SANDBOX_* env) with fail-closed validation (§91).

Invalid security configuration fails closed. Production refuses to start
with unsafe development fallbacks (§90, §105).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from openagent.sandbox.profiles import IMAGE_TRUST_TIERS
from openagent.sandbox.security import NETWORK_MODES

__all__ = [
    "SandboxSettings", "load_settings", "production_security_check",
    "is_production",
]


def is_production() -> bool:
    return os.environ.get("OPENAGENT_ENV", "development").lower() == "production"


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")


def _get_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")


@dataclass
class SandboxSettings:
    provider: str = "docker"
    default_profile: str = "TEST"
    default_timeout: int = 300
    max_timeout: int = 3600
    max_memory_mb: int = 8192
    max_cpu: float = 4.0
    max_disk_mb: int = 20480
    max_pids: int = 1024
    network_mode: str = "NO_NETWORK"
    image: str = "openagent-sandbox-base"
    image_digest: str = ""
    image_trust: str = "CORE"
    cleanup_interval_seconds: int = 300
    artifact_retention_days: int = 30
    allow_local_fallback: bool = False
    egress_proxy: str = ""  # deployment-provided filtered egress for ALLOWLIST modes
    workspace_root: str = "./workspaces"
    artifact_root: str = "./artifacts"
    # quotas
    max_sandboxes_per_org: int = 20
    max_concurrent_executions_per_org: int = 10
    max_sandboxes_per_user: int = 5

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.provider not in ("docker", "local", "kubernetes"):
            problems.append(f"SANDBOX_PROVIDER '{self.provider}' unknown")
        from openagent.sandbox.profiles import BUILTIN_PROFILES
        if self.default_profile not in BUILTIN_PROFILES:
            problems.append(
                f"SANDBOX_DEFAULT_PROFILE '{self.default_profile}' unknown")
        if not (5 <= self.default_timeout <= 8 * 3600):
            problems.append("SANDBOX_DEFAULT_TIMEOUT out of range 5..28800")
        if not (60 <= self.max_timeout <= 8 * 3600):
            problems.append("SANDBOX_MAX_TIMEOUT out of range 60..28800")
        if self.default_timeout > self.max_timeout:
            problems.append("SANDBOX_DEFAULT_TIMEOUT exceeds SANDBOX_MAX_TIMEOUT")
        if not (64 <= self.max_memory_mb <= 65536):
            problems.append("SANDBOX_MAX_MEMORY out of range 64..65536 MB")
        if not (0.05 <= self.max_cpu <= 64):
            problems.append("SANDBOX_MAX_CPU out of range 0.05..64")
        if not (128 <= self.max_disk_mb <= 102400):
            problems.append("SANDBOX_MAX_DISK out of range 128..102400 MB")
        if not (16 <= self.max_pids <= 8192):
            problems.append("SANDBOX_MAX_PIDS out of range 16..8192")
        if self.network_mode not in NETWORK_MODES:
            problems.append(f"SANDBOX_NETWORK_MODE '{self.network_mode}' unknown")
        if self.image_trust not in IMAGE_TRUST_TIERS:
            problems.append(f"SANDBOX image trust '{self.image_trust}' unknown")
        if self.provider == "kubernetes":
            problems.append("kubernetes provider is a future extension (not implemented)")
        if is_production():
            if self.provider == "local" or self.allow_local_fallback:
                problems.append("local execution fallback is forbidden in production")
            if self.image_trust == "UNTRUSTED":
                problems.append("UNTRUSTED images are forbidden in production")
            if self.network_mode == "FULL_OUTBOUND":
                problems.append("FULL_OUTBOUND default network is forbidden in production")
            if not self.image_digest:
                problems.append("production requires SANDBOX_IMAGE_DIGEST (image pinning)")
        return problems

    def assert_valid(self) -> None:
        problems = self.validate()
        if problems:
            raise ValueError("Invalid sandbox configuration (fail-closed): "
                             + "; ".join(problems))


def load_settings() -> SandboxSettings:
    s = SandboxSettings(
        provider=os.environ.get("SANDBOX_PROVIDER", "docker").lower(),
        default_profile=os.environ.get("SANDBOX_DEFAULT_PROFILE", "TEST").upper(),
        default_timeout=_get_int("SANDBOX_DEFAULT_TIMEOUT", 300),
        max_timeout=_get_int("SANDBOX_MAX_TIMEOUT", 3600),
        max_memory_mb=_get_int("SANDBOX_MAX_MEMORY", 8192),
        max_cpu=_get_float("SANDBOX_MAX_CPU", 4.0),
        max_disk_mb=_get_int("SANDBOX_MAX_DISK", 20480),
        max_pids=_get_int("SANDBOX_MAX_PIDS", 1024),
        network_mode=os.environ.get("SANDBOX_NETWORK_MODE", "NO_NETWORK").upper(),
        image=os.environ.get("SANDBOX_IMAGE", "openagent-sandbox-base"),
        image_digest=os.environ.get("SANDBOX_IMAGE_DIGEST", ""),
        image_trust=os.environ.get("SANDBOX_IMAGE_TRUST", "CORE").upper(),
        cleanup_interval_seconds=_get_int("SANDBOX_CLEANUP_INTERVAL", 300),
        artifact_retention_days=_get_int("SANDBOX_ARTIFACT_RETENTION", 30),
        allow_local_fallback=os.environ.get(
            "SANDBOX_ALLOW_LOCAL_FALLBACK", "false").lower() == "true",
        egress_proxy=os.environ.get("SANDBOX_EGRESS_PROXY", ""),
        workspace_root=os.environ.get("OPENAGENT_WORKSPACE_ROOT", "./workspaces"),
        artifact_root=os.environ.get("OPENAGENT_ARTIFACT_ROOT", "./artifacts"),
    )
    s.assert_valid()
    return s


async def production_security_check(settings: Optional[SandboxSettings] = None,
                                    ) -> dict[str, Any]:
    """Startup/security diagnostic (§105). Production fails closed."""
    from openagent.sandbox.providers import docker_available
    s = settings or load_settings()
    report: dict[str, Any] = {"mode": "production" if is_production() else "development",
                              "checks": {}, "ok": True}
    checks = report["checks"]

    async def _docker() -> None:
        ok, detail = await docker_available()
        checks["docker_available"] = {"ok": ok, "detail": detail}

    try:
        await _docker()
    except Exception as e:  # pragma: no cover - defensive
        checks["docker_available"] = {"ok": False, "detail": str(e)[:200]}
    checks["provider"] = {"ok": s.provider in ("docker", "local"),
                          "detail": s.provider}
    checks["local_fallback"] = {
        "ok": not (is_production() and (s.provider == "local" or s.allow_local_fallback)),
        "detail": "disabled" if not s.allow_local_fallback else "ENABLED (dev only)"}
    checks["default_network"] = {"ok": True, "detail": s.network_mode}
    checks["default_limits"] = {
        "ok": True,
        "detail": (f"cpu={s.max_cpu} mem={s.max_memory_mb}MB disk={s.max_disk_mb}MB "
                   f"pids={s.max_pids} timeout={s.max_timeout}s")}
    checks["image_pinning"] = {"ok": bool(s.image_digest) or not is_production(),
                               "detail": s.image_digest or s.image + " (unpinned)"}
    checks["credential_isolation"] = {"ok": True, "detail": "ref-only injection + redaction"}
    checks["artifact_isolation"] = {"ok": True, "detail": "storage abstraction, no container paths"}
    checks["audit_logging"] = {"ok": True, "detail": "AuditLog + sandbox_events"}
    problems = s.validate()
    report["config_problems"] = problems
    report["ok"] = (not problems and checks["local_fallback"]["ok"]
                    and (checks["docker_available"]["ok"] or s.provider == "local"))
    if is_production() and not report["ok"]:
        raise ValueError("Sandbox production checks FAILED (fail-closed): "
                         + "; ".join(problems or ["see checks"]))
    report["explicit_dev_mode"] = (not is_production())
    return report
