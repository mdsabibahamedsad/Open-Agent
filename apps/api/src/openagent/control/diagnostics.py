"""MP26: diagnostics + support bundles + exports (§105-108).

Self-hosted first: diagnostics run without cloud dependencies and never
expose secrets. Support bundles contain sanitized health/config/metrics
summaries only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

DIAGNOSTIC_COMPONENTS = ("configuration", "database", "queue", "workers",
                         "storage", "scheduler", "sandbox", "browser",
                         "model_providers", "connectors", "mcp")


@dataclass
class DiagnosticResult:
    component: str
    ok: bool
    message: str
    action: str = ""
    checked_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        from openagent.control.observability import redact
        return {"component": self.component, "ok": self.ok,
                "message": redact(self.message), "action": self.action,
                "checked_at": self.checked_at.isoformat()}


CheckFn = Callable[[], tuple[bool, str, str]]


class Diagnostics:
    """Pluggable diagnostics runner (checks registered per deployment)."""

    def __init__(self) -> None:
        self._checks: dict[str, CheckFn] = {}

    def register(self, component: str, check: CheckFn) -> None:
        if component not in DIAGNOSTIC_COMPONENTS:
            raise ValueError(f"unknown diagnostic component {component}")
        self._checks[component] = check

    def run(self, components: Optional[list[str]] = None) -> list[DiagnosticResult]:
        wanted = components or list(DIAGNOSTIC_COMPONENTS)
        results: list[DiagnosticResult] = []
        for component in wanted:
            check = self._checks.get(component)
            if check is None:
                results.append(DiagnosticResult(
                    component, True, "no check registered (unknown state)",
                    action="register a check for this component"))
                continue
            try:
                ok, message, action = check()
                results.append(DiagnosticResult(component, ok, message, action))
            except Exception as exc:
                results.append(DiagnosticResult(
                    component, False, f"check errored: {exc}",
                    action="inspect component logs"))
        return results

    def summary(self, results: list[DiagnosticResult]) -> dict[str, Any]:
        failed = [r.component for r in results if not r.ok]
        return {"checked": len(results), "failed": failed,
                "healthy": not failed}


def build_support_bundle(*, version: str, health: dict[str, Any],
                         config: dict[str, Any],
                         metrics: dict[str, Any],
                         recent_errors: list[str],
                         components: dict[str, str]) -> dict[str, Any]:
    """Sanitized support bundle (§107). Secrets can never enter."""
    from openagent.control.observability import redact
    return {"version": version, "built_at": datetime.now(timezone.utc).isoformat(),
            "health": redact(health), "config": redact(config),
            "metrics_summary": redact(metrics),
            "recent_errors": redact(recent_errors[:50]),
            "components": dict(components),
            "excludes": ["passwords", "tokens", "raw credentials",
                         "private keys", "user content"]}


def export_scope(rows: list[dict[str, Any]], *, allowed_fields: list[str],
                 limit: int = 10000) -> list[dict[str, Any]]:
    """Permission-respecting export: only allowed fields, capped rows."""
    from openagent.control.observability import redact
    out = []
    for row in rows[:max(1, limit)]:
        out.append(redact({k: row.get(k) for k in allowed_fields if k in row}))
    return out
