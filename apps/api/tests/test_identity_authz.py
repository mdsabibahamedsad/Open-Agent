"""MP27 unit: ABAC, policy engine + simulator, sessions/trust,
step-up, tokens, MFA."""

import time

import pytest

from openagent.identity.abac import (
    Authorizer, AuthzRequest, abac_rule, classification_gate, rbac_allow,
)
from openagent.identity.mfa import (
    MfaPolicy, auth_strength_for, new_totp_secret, totp_now,
    verify_totp,
)
from openagent.identity.secpolicies import (
    PolicySimulator, PolicyStore, SecurityPolicy, detect_drift,
    posture_report,
)
from openagent.identity.tokensvc import TokenService
from openagent.identity.trust import (
    Device, RevocationRegistry, SessionContext, evaluate_step_up,
    session_risk,
)
from openagent.identity.types import AuthStrength, DeviceTrust


def test_authorizer_layers_and_deny_default():
    authorizer = Authorizer()
    assert not authorizer.decide(AuthzRequest(
        identity_id="u", identity_type="human", action="anything")).allowed
    authorizer.add("platform", "rbac", rbac_allow(
        "rbac", permissions={"workflow.execute"}))
    decision = authorizer.decide(AuthzRequest(
        identity_id="u", identity_type="human",
        action="workflow.execute"))
    assert decision.allowed and "rbac" in decision.policy_ids


def test_abac_restricts_by_environment():
    authorizer = Authorizer()
    authorizer.add("platform", "rbac", rbac_allow(
        "rbac", permissions={"deploy"}))
    authorizer.add("environment", "prod-gate", abac_rule(
        "prod-gate", forbid={"environment": "PRODUCTION"}))
    prod = AuthzRequest(identity_id="u", identity_type="human",
                        action="deploy",
                        attributes={"environment": "PRODUCTION"})
    assert not authorizer.decide(prod).allowed
    dev = AuthzRequest(identity_id="u", identity_type="human",
                       action="deploy",
                       attributes={"environment": "DEVELOPMENT"})
    assert authorizer.decide(dev).allowed


def test_policy_errors_fail_closed():
    authorizer = Authorizer()

    def _boom(request):
        raise RuntimeError("policy backend down")

    authorizer.add("platform", "boom", _boom)
    assert not authorizer.decide(AuthzRequest(
        identity_id="u", identity_type="human", action="x")).allowed


def test_classification_gate_needs_purpose():
    gate = classification_gate()
    secret = AuthzRequest(identity_id="u", identity_type="human",
                          action="read",
                          attributes={"data_classification": "SECRET"})
    assert gate(secret) is not None and not gate(secret).allowed
    justified = AuthzRequest(
        identity_id="u", identity_type="human", action="read",
        attributes={"data_classification": "SECRET",
                    "purpose": "incident response"})
    assert gate(justified) is None  # abstains; other layers decide


def test_abac_rejects_unknown_attributes():
    with pytest.raises(ValueError):
        abac_rule("x", require={"favorite_color": "blue"})


def test_policy_store_versions_and_rollback():
    store = PolicyStore()
    policy = store.put(SecurityPolicy(scope="organization",
                                      scope_id="o1", sections={
                                          "mfa": {"required": True}}),
                       actor="admin", reason="harden")
    assert policy.version == 1
    store.put(SecurityPolicy(policy_id=policy.policy_id,
                             scope="organization", scope_id="o1",
                             sections={"mfa": {"required": False}}),
              actor="admin", reason="relax")
    assert store._policies[policy.policy_id].version == 2
    store.put(SecurityPolicy(policy_id=policy.policy_id,
                             scope="organization", scope_id="o1",
                             sections={"mfa": {"required": True},
                                       "session": {"ttl": 60}}),
              actor="admin", reason="tune")
    # Multi-step rollback (3 -> 1) requires explicit confirmation.
    with pytest.raises(ValueError):
        store.rollback(policy.policy_id, 1, actor="admin",
                       reason="undo")
    rolled = store.rollback(policy.policy_id, 1, actor="admin",
                            reason="undo", confirmed=True)
    assert rolled.sections == {"mfa": {"required": True}}
    assert len(store.audit()) == 4


def test_simulator_safe_explanations():
    store = PolicyStore()
    policy = store.put(SecurityPolicy(
        scope="organization", scope_id="o1",
        sections={"mfa": {"required": True},
                  "environment": {"deny_environments": ["PRODUCTION"]},
                  "data": {"purpose_required_for": ["SECRET"]}}),
        actor="admin")
    simulator = PolicySimulator(store)
    from openagent.identity.secpolicies import SimulationInput
    denied = simulator.evaluate(policy.policy_id, SimulationInput(
        actor="u", action="deploy", resource="api",
        environment="PRODUCTION", context={}))
    assert denied.verdict in ("DENY", "STEP_UP")
    assert "MFA" in denied.explanation or "PRODUCTION" in denied.explanation
    assert "secret" not in denied.explanation.lower()
    unknown = simulator.evaluate("missing", SimulationInput(
        actor="u", action="x", resource="y"))
    assert unknown.verdict == "DENY"


def test_posture_and_drift():
    report = posture_report(mfa="Required", sso="Configured",
                            scim="Active", audit="Enabled",
                            ip_restrictions="Configured",
                            open_issues=["1 open alert"])
    assert "score" not in str(report).lower()
    assert report["MFA"] == "Required"
    drifts = detect_drift({"mfa_required": True}, {"mfa_required": False})
    assert len(drifts) == 1 and "Drift detected" in drifts[0]["message"]
    assert detect_drift({"a": 1}, {"a": 1}) == []


def test_session_risk_and_step_up():
    calm = session_risk(SessionContext(
        session_id="s", user_id="u", auth_strength="AAL2",
        device_trust=DeviceTrust.TRUSTED, ip_allowed=True,
        mfa_verified=True))
    assert calm["level"] == "LOW"
    risky = session_risk(SessionContext(
        session_id="s", user_id="u", new_device=True, failed_attempts=5,
        device_trust=DeviceTrust.RESTRICTED, ip_allowed=False,
        session_age_seconds=99999))
    assert risky["level"] == "HIGH"
    decision = evaluate_step_up(action="production_action",
                                have_strength="AAL1", risk_level="LOW")
    assert decision.verdict == "STEP_UP"
    assert decision.required_strength == "AAL2"
    allowed = evaluate_step_up(action="read_dashboard",
                               have_strength="AAL1", risk_level="LOW")
    assert allowed.verdict == "ALLOW"


def test_revocation_is_prompt():
    registry = RevocationRegistry()
    assert registry.valid("sess:1", 0)
    registry.revoke("sess:1")
    assert not registry.valid("sess:1", 0)
    registry.revoke_user_everywhere("u1")
    assert not registry.valid("user:u1", 0)


def test_device_revocation():
    device = Device(user_id="u1")
    assert device.usable()[0]
    device.revoke()
    assert not device.usable()[0]
    assert device.trust == DeviceTrust.REVOKED


def test_token_service_lifecycle():
    service = TokenService()
    raw, record = service.mint("access", "u1", organization_id="o1",
                               scope="read")
    assert service.verify(raw, kind="access").subject == "u1"
    with pytest.raises(ValueError):
        service.verify(raw, kind="refresh")  # kind mismatch
    with pytest.raises(ValueError):
        service.mint("access", "admin", perpetual=True)  # never perpetual
    rotated, _ = service.rotate(raw)
    assert service.verify(rotated).subject == "u1"
    with pytest.raises(ValueError):
        service.verify(raw)  # old token dead after rotation
    jwt = service.mint_jwt(service.verify(rotated), "jwt-secret")
    assert service.verify_jwt(jwt, secret="jwt-secret").subject == "u1"
    with pytest.raises(ValueError):
        service.verify_jwt(jwt, secret="wrong-secret")


def test_totp_roundtrip_and_window():
    secret = new_totp_secret()
    now = time.time()
    code = totp_now(secret, now=now)
    assert verify_totp(code, secret, now=now)
    assert not verify_totp("000000", secret, now=now)
    assert verify_totp(code, secret, now=now + 30)  # adjacent window
    assert not verify_totp(code, secret, now=now + 300)


def test_mfa_policy_and_strength():
    policy = MfaPolicy(required_teams=["oncall"])
    assert policy.requires_mfa(is_admin=False, teams=["oncall"])[0]
    assert not policy.requires_mfa(is_admin=False, teams=["docs"])[0]
    assert not policy.allows_bypass(scope="organization")
    assert auth_strength_for(["password"]) == "AAL1"
    assert auth_strength_for(["password", "totp"]) == "AAL2"
    assert auth_strength_for(["webauthn"]) == "AAL3"
