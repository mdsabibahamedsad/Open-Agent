"""MP26 unit: reliability — health, alerts, incidents, maintenance,
deployments/rollback, reconciliation, operation locks."""

from datetime import datetime, timedelta, timezone

from openagent.control.reliability import (
    AlertEngine, AlertRule, Controller, HealthCheck, Incident,
    MaintenanceWindow, MemoryController, OperationLock,
    reconcile, rollback_plan, summarize_health,
)
from openagent.control.types import HealthState


def test_health_worst_wins_empty_unknown():
    assert summarize_health([])["status"] == HealthState.UNKNOWN
    checks = [HealthCheck("api", "liveness", "HEALTHY"),
              HealthCheck("queue", "dependency", "DEGRADED")]
    summary = summarize_health(checks)
    assert summary["status"] == "DEGRADED"
    assert summary["components"]["workers"] == "UNKNOWN"
    assert summary["public"] == "degraded"


def test_health_check_validation():
    ok, _ = HealthCheck("api", "liveness", "HEALTHY").validate()
    assert ok
    ok, _ = HealthCheck("nope", "liveness", "HEALTHY").validate()
    assert not ok
    ok, _ = HealthCheck("api", "vibes", "HEALTHY").validate()
    assert not ok


def test_alert_rule_rejects_code_conditions():
    rule = AlertRule(rule_id="r1", metric="queue.depth",
                     condition="eval('1')", threshold=5)
    assert not rule.validate()[0]
    rule = AlertRule(rule_id="r1", metric="queue.depth",
                     condition="gt", threshold=1000,
                     duration_seconds=300, severity="CRITICAL")
    assert rule.validate()[0]


def test_alert_engine_fires_dedups_resolves():
    engine = AlertEngine()
    rule = AlertRule(rule_id="r1", metric="queue.depth", condition="gt",
                     threshold=1000, severity="CRITICAL")
    first = engine.evaluate(rule, 1500, source="q1")
    assert first is not None and first.severity == "CRITICAL"
    assert engine.evaluate(rule, 1600, source="q1") is None  # dedup
    assert engine.evaluate(rule, 10, source="q1") is None  # resolves
    assert engine.open_alerts() == []
    assert engine.acknowledge("missing") is None


def test_alert_acknowledge():
    engine = AlertEngine()
    rule = AlertRule(rule_id="r1", metric="m", condition="gt", threshold=1)
    alert = engine.evaluate(rule, 5, source="s")
    assert alert is not None
    assert engine.acknowledge(alert.alert_id) is not None


def test_incident_lifecycle_and_timeline():
    incident = Incident(title="queue overload", severity="CRITICAL")
    assert incident.status == "DETECTED"
    ok, _ = incident.transition("RESOLVED", "op-1")
    assert not ok  # skips are rejected
    ok, _ = incident.transition("ACKNOWLEDGED", "op-1")
    assert ok
    ok, _ = incident.transition("INVESTIGATING", "op-1", "checking")
    assert ok
    assert len(incident.timeline) == 2  # one event per transition
    # Timeline is append-only: transitions only add events.
    before = len(incident.timeline)
    incident.append("op-1", "note")
    assert len(incident.timeline) == before + 1


def test_maintenance_window_bounds():
    now = datetime.now(timezone.utc)
    window = MaintenanceWindow(starts_at=now - timedelta(hours=1),
                               ends_at=now + timedelta(hours=1),
                               affected=["api"])
    assert window.is_active(now)
    assert not window.is_active(now + timedelta(hours=2))


def test_rollback_blocks_destructive_migrations():
    blocked = rollback_plan(current_version="1.2", target_version="1.1",
                            migrations_since=["025_add_control_plane"],
                            destructive_migrations=["025_add_control_plane"])
    assert not blocked["allowed"]
    allowed = rollback_plan(current_version="1.2", target_version="1.1",
                            migrations_since=["025_add_control_plane"],
                            destructive_migrations=[])
    assert allowed["allowed"] and allowed["steps"]
    assert not rollback_plan(current_version="1.1", target_version="1.1",
                             migrations_since=[],
                             destructive_migrations=[])["allowed"]


def test_reconcile_diff_and_controller():
    diffs = reconcile({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 9})
    actions = {d.key: d.action for d in diffs}
    assert actions == {"a": "noop", "b": "update", "c": "delete"}
    controller = MemoryController("pools", {"workers": 4})
    result = controller.run_once()
    assert result["verified"] and result["applied"] == 1
    assert controller.run_once()["applied"] == 0  # idempotent


def test_operation_lock_excludes_concurrent_admins():
    locks = OperationLock()
    ok, _ = locks.acquire("region:eu-1", "admin-A")
    assert ok
    ok, reason = locks.acquire("region:eu-1", "admin-B")
    assert not ok and "admin-A" in reason
    locks.release("region:eu-1", "admin-A")
    ok, _ = locks.acquire("region:eu-1", "admin-B")
    assert ok


def test_dry_run_never_applies():
    locks = OperationLock()
    preview = locks.dry_run_drain("region:eu-1",
                                  {"workers": 12, "executions": 40})
    assert preview["applied"] is False
    assert preview["would_impact"] == {"workers": 12, "executions": 40}
