"""MP26 unit: enterprise controls + privileged ops + diagnostics."""

from datetime import datetime, timedelta, timezone

import pytest

from openagent.control.diagnostics import (
    Diagnostics, build_support_bundle, export_scope,
)
from openagent.control.enterprise import (
    ApiKeyPolicy, PrivateEnrollment, RotationJob, SessionPolicy,
    apply_preset, classify, compliance_checklist, ip_allowed,
    merge_retention, risk_score, trusted_source_ip,
)
from openagent.control.privileged import (
    AuditChain, PrivilegedAuditRecord, StepUpRequirement,
    classify_operation, step_up_satisfied,
)
from openagent.control.types import ActionRisk


def test_ip_allow_deny():
    assert ip_allowed("10.1.2.3", allowlist=["10.0.0.0/8"],
                      denylist=[])[0]
    assert not ip_allowed("192.168.1.1", allowlist=["10.0.0.0/8"],
                          denylist=[])[0]
    assert not ip_allowed("10.1.2.3", allowlist=["10.0.0.0/8"],
                          denylist=["10.1.0.0/16"])[0]
    assert not ip_allowed("not-an-ip", allowlist=[], denylist=[])[0]
    # Opt-in feature: no policy configured means allowed.
    assert ip_allowed("8.8.8.8", allowlist=[], denylist=[])[0]


def test_untrusted_proxy_headers_ignored():
    # Direct connection: client header is NEVER trusted.
    assert trusted_source_ip(forwarded_for="1.2.3.4",
                             remote_addr="9.9.9.9",
                             trusted_proxies=[]) == "9.9.9.9"
    # Trusted proxy: first forwarded address counts.
    assert trusted_source_ip(forwarded_for="1.2.3.4, 5.6.7.8",
                             remote_addr="10.0.0.1",
                             trusted_proxies=["10.0.0.0/8"]) == "1.2.3.4"


def test_session_policy_timeouts():
    policy = SessionPolicy(lifetime_minutes=60, idle_timeout_minutes=10)
    now = datetime.now(timezone.utc)
    expired, _ = policy.expired(now - timedelta(hours=2), now)
    assert expired
    idle, reason = policy.expired(now - timedelta(minutes=30),
                                  now - timedelta(minutes=20))
    assert idle and "idle" in reason
    forced = SessionPolicy(force_logout=True)
    assert forced.expired(now, now)[0]
    assert not SessionPolicy(idle_timeout_minutes=99999,
                             lifetime_minutes=60).validate()[0]


def test_api_key_policy():
    policy = ApiKeyPolicy(require_expiry=True, max_lifetime_days=30,
                          require_scopes=True)
    assert not policy.validate_new(
        scopes=[], expires_at=None)[0]
    future = datetime.now(timezone.utc) + timedelta(days=400)
    assert not policy.validate_new(scopes=["read"],
                                   expires_at=future)[0]
    ok, _ = policy.validate_new(
        scopes=["read"],
        expires_at=datetime.now(timezone.utc) + timedelta(days=7))
    assert ok


def test_rotation_never_causes_downtime():
    job = RotationJob(kind="api_key", ref="key_1")
    assert job.stage == "created"
    ok, _ = job.advance(True)
    assert ok and job.stage == "propagating"
    ok, message = job.advance(False, "vault unreachable")
    assert not ok and job.stage == "failed"
    assert "retained" in message  # old secret stays live


def test_retention_floors_cannot_be_bypassed():
    merged, clamped = merge_retention({"audit_logs": 100, "logs": 50},
                                      {"audit_logs": 1, "logs": 999})
    assert merged["audit_logs"] == 100
    assert "audit_logs" in clamped
    assert merged["logs"] == 999


def test_presets_are_bundles():
    strict = apply_preset("strict")
    assert strict["mfa_required"] is True
    custom = apply_preset("custom", {"mfa_required": True})
    assert custom["mfa_required"] is True
    with pytest.raises(ValueError):
        apply_preset("marketing")


def test_classify_defaults_conservative():
    assert classify("public blog post") == "PUBLIC"
    assert classify("db password rotation") == "CONFIDENTIAL"
    assert classify("x", requested="RESTRICTED") == "RESTRICTED"


def test_enrollment_single_use_expiring():
    enrollment, raw = PrivateEnrollment.mint("org-1", ttl_hours=1)
    ok, _ = enrollment.redeem(raw, "worker-9")
    assert ok
    ok, reason = enrollment.redeem(raw, "worker-9")
    assert not ok and "used" in reason
    stale, raw2 = PrivateEnrollment.mint("org-1")
    stale.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert not stale.redeem(raw2, "w")[0]


def test_risk_score_needs_correlation():
    single = risk_score({"api_request_spike": 0.95})
    assert single["level"] in ("LOW", "MEDIUM")  # never HIGH alone
    assert "human review" in single["note"]
    multi = risk_score({"api_request_spike": 0.9, "auth_failure_spike": 0.9,
                        "credential_abuse": 0.85})
    assert multi["level"] == "HIGH"
    assert risk_score({})["score"] == 0.0


def test_compliance_never_claims_certification():
    checklist = compliance_checklist("SOC2")
    assert checklist["certified"] is False
    assert "no certification" in checklist["disclaimer"].lower()
    with pytest.raises(ValueError):
        compliance_checklist("PCI-DSS-LEVEL-99")


def test_operation_classification_and_step_up():
    assert classify_operation("emergency.shutdown") == ActionRisk.CRITICAL
    assert classify_operation("something.unknown") == ActionRisk.SENSITIVE
    requirement = StepUpRequirement.for_operation("emergency.shutdown")
    assert requirement.require_mfa and requirement.require_phrase == "CONFIRM"
    now = datetime.now(timezone.utc)
    ok, _ = step_up_satisfied(
        requirement, last_auth_at=now, mfa_verified=True,
        phrase="CONFIRM", reauthed=True)
    assert ok
    # Old session alone never suffices for critical ops.
    old = now - timedelta(hours=5)
    assert not step_up_satisfied(
        requirement, last_auth_at=old, mfa_verified=True,
        phrase="CONFIRM", reauthed=True)[0]
    normal = StepUpRequirement.for_operation("health.read")
    assert normal.risk == ActionRisk.SENSITIVE  # unknown ops fail safe


def test_audit_chain_tamper_evident_and_sanitized():
    chain = AuditChain()
    ok, _ = chain.append(PrivilegedAuditRecord(
        actor="master", action="region.drain", resource="eu-1",
        before={"workers": 4}, after={"workers": 0},
        ip="10.0.0.1", request_id="req_1", reason=" drill",
        result="ok"))
    assert ok
    record = chain.records()[0]
    assert "chain_hash" in record and record["ip"] == "10.0.0.1"
    secret_record = PrivilegedAuditRecord(
        actor="m", action="credentials.rotate_critical", resource="vault",
        after={"api_key": "sk-live-123"})
    chain.append(secret_record)
    assert chain.records()[-1]["after"] == {"api_key": "[REDACTED]"}
    assert chain.verify()[0]
    chain.records()[0]["action"] = "tampered"
    assert not chain.verify()[0]


def test_diagnostics_and_support_bundle():
    diagnostics = Diagnostics()
    diagnostics.register("database", lambda: (True, "ok", ""))
    with pytest.raises(ValueError):
        diagnostics.register("teleporter", lambda: (True, "ok", ""))
    results = diagnostics.run(["database", "queue"])
    assert diagnostics.summary(results)["healthy"]
    bundle = build_support_bundle(
        version="0.1.0", health={"api": "HEALTHY"},
        config={"SECRET_KEY": "shh"}, metrics={}, recent_errors=[],
        components={"api": "HEALTHY"})
    assert bundle["config"] == {"SECRET_KEY": "[REDACTED]"}
    assert "passwords" in bundle["excludes"]
    rows = export_scope([{"a": 1, "password": "x"}], allowed_fields=["a"])
    assert rows == [{"a": 1}]
