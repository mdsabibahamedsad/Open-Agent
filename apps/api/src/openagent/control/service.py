"""MP26: control-plane service facade.

Assembles configuration resolution, feature flags, policy resolution,
health, alerts, incidents, telemetry and audit into one injectable
surface for the API layer. Pure-logic defaults work self-hosted with
no cloud dependency; DB-backed state is layered by the API routes.
"""

from __future__ import annotations

from typing import Any, Optional

from openagent.control.configuration import ConfigEntry, resolve_all
from openagent.control.diagnostics import Diagnostics
from openagent.control.feature_flags import FlagEvaluator
from openagent.control.observability import Telemetry, Tracer
from openagent.control.policies import PolicyResolver
from openagent.control.privileged import AuditChain
from openagent.control.reliability import AlertEngine, OperationLock


class ControlPlaneService:
    def __init__(self) -> None:
        self.config_entries: list[ConfigEntry] = []
        self.flags = FlagEvaluator()
        self.policies = PolicyResolver()
        self.telemetry = Telemetry()
        self.tracer = Tracer(self.telemetry)
        self.alerts = AlertEngine()
        self.locks = OperationLock()
        self.audit = AuditChain()
        self.diagnostics = Diagnostics()

    # ------------------------------------------------------------ config ---
    def set_config(self, entry: ConfigEntry) -> None:
        self.config_entries = [e for e in self.config_entries
                               if not (e.scope == entry.scope
                                       and e.scope_id == entry.scope_id
                                       and e.category == entry.category
                                       and e.key == entry.key)]
        self.config_entries.append(entry)

    def resolved_config(self) -> dict[str, dict[str, Any]]:
        return resolve_all(self.config_entries)

    def health_snapshot(self) -> dict[str, Any]:
        from openagent.control.reliability import summarize_health
        return summarize_health([])


_service: Optional[ControlPlaneService] = None


def get_control_service() -> ControlPlaneService:
    global _service
    if _service is None:
        _service = ControlPlaneService()
    return _service


def reset_control_service() -> None:
    global _service
    _service = None
