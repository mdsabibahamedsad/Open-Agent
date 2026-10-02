"""MP26 unit: feature flags (strategies, determinism, security guard,
kill switches)."""

from openagent.control.feature_flags import (
    FeatureFlag, FlagEvaluator, is_security_flag,
)


def test_boolean_flag():
    evaluator = FlagEvaluator([FeatureFlag(key="ui.new", scope="PLATFORM",
                                           strategy="boolean", enabled=True)])
    assert evaluator.evaluate("ui.new", subject_id="u1").allowed


def test_percentage_rollout_deterministic():
    flag = FeatureFlag(key="rollout.x", scope="PLATFORM",
                       strategy="percentage", percentage=50.0)
    evaluator = FlagEvaluator([flag])
    first = evaluator.evaluate("rollout.x", subject_id="user-42")
    # Same subject -> same bucket every request (no per-request randomness).
    for _ in range(5):
        assert evaluator.evaluate("rollout.x",
                                  subject_id="user-42").allowed == first.allowed


def test_allowlist_denylist():
    evaluator = FlagEvaluator([
        FeatureFlag(key="beta", scope="ORGANIZATION", strategy="allowlist",
                    allowlist=["u1"]),
        FeatureFlag(key="open", scope="PLATFORM", strategy="denylist",
                    denylist=["bad"]),
    ])
    assert evaluator.evaluate("beta", subject_id="u1").allowed
    assert not evaluator.evaluate("beta", subject_id="u2").allowed
    assert evaluator.evaluate("open", subject_id="good").allowed
    assert not evaluator.evaluate("open", subject_id="bad").allowed


def test_security_flags_are_guarded():
    assert is_security_flag("security.mfa_required")
    assert is_security_flag("approval.bypass")
    assert not is_security_flag("ui.new_nav")
    evaluator = FlagEvaluator([FeatureFlag(key="security.mfa_required",
                                            scope="PLATFORM",
                                            strategy="boolean", enabled=True)])
    decision = evaluator.evaluate("security.mfa_required", subject_id="u1")
    assert decision.security_guarded  # advisory only; never a bypass


def test_narrow_scope_wins():
    evaluator = FlagEvaluator([
        FeatureFlag(key="x", scope="PLATFORM", strategy="boolean",
                    enabled=False),
        FeatureFlag(key="x", scope="ORGANIZATION", scope_id="o1",
                    strategy="boolean", enabled=True),
    ])
    decision = evaluator.evaluate(
        "x", subject_id="u1",
        scope_chain=[("PLATFORM", ""), ("ORGANIZATION", "o1")])
    assert decision.allowed


def test_kill_switch_engaged_disables_capability():
    evaluator = FlagEvaluator([FeatureFlag(key="kill.connector.slack",
                                            scope="PLATFORM",
                                            strategy="boolean", enabled=True)])
    decision = evaluator.kill_switch("connector", "slack")
    assert not decision.allowed and "kill switch" in decision.reason


def test_kill_switch_unknown_target_rejected():
    evaluator = FlagEvaluator()
    decision = evaluator.kill_switch("teleporter", "x")
    assert not decision.allowed


def test_kill_switch_default_operational():
    evaluator = FlagEvaluator()
    assert evaluator.kill_switch("region", "eu-1").allowed
