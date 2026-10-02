"""MP26 unit: resource hierarchy, config precedence, policy resolution."""

from openagent.control.configuration import (
    ConfigEntry, preview_change, resolve_all, resolve_config,
)
from openagent.control.policies import (
    PolicyDecision, PolicyResolver, environment_allows,
)
from openagent.control.resources import (
    ResourceRef, check_inheritance, environment_isolated,
    hierarchy_for, permission_scope_chain,
)


def test_resource_validation():
    ok, _ = ResourceRef(id="w1", type="worker",
                        organization_id="o1").validate()
    assert ok
    ok, reason = ResourceRef(id="w1", type="worker").validate()
    assert not ok and "organization_id" in reason
    ok, reason = ResourceRef(id="x", type="starship",
                             organization_id="o1").validate()
    assert not ok


def test_hierarchy_scopes_broad_first():
    ref = ResourceRef(id="e1", type="execution", organization_id="o1",
                      project_id="p1", environment="PRODUCTION")
    path = hierarchy_for(ref)
    assert [s for s, _ in path.scopes()] == [
        "platform", "organization", "project", "environment"]
    assert permission_scope_chain(path) == [
        "platform", "org:o1", "project:p1", "env:PRODUCTION"]


def test_inheritance_broad_covers_narrow_never_reverse():
    from openagent.control.resources import HierarchyPath
    narrow = HierarchyPath(organization_id="o1", project_id="p1",
                           environment="PRODUCTION")
    assert check_inheritance("platform", narrow)
    assert check_inheritance("org:o1", narrow)
    assert not check_inheritance("org:o2", narrow)
    assert not check_inheritance("project:p1", HierarchyPath(
        organization_id="o1"))  # narrow grant never covers broader resource
    assert not check_inheritance("bogus", narrow)


def test_environment_isolation():
    assert environment_isolated("PRODUCTION", "PRODUCTION")
    assert not environment_isolated("PRODUCTION", "DEVELOPMENT")
    assert not environment_isolated("", "PRODUCTION")


def test_config_precedence_narrow_wins():
    entries = [
        ConfigEntry(scope="PLATFORM", scope_id="", category="runtime",
                    key="timeout", value=300),
        ConfigEntry(scope="ORGANIZATION", scope_id="o1", category="runtime",
                    key="timeout", value=120),
    ]
    value, winner = resolve_config(entries, category="runtime", key="timeout")
    assert value == 120 and winner is not None and winner.scope == "ORGANIZATION"


def test_security_restriction_cannot_be_relaxed():
    entries = [
        ConfigEntry(scope="PLATFORM", scope_id="", category="security",
                    key="network_policy", value="INTERNAL_ONLY"),
        ConfigEntry(scope="PROJECT", scope_id="p1", category="security",
                    key="network_policy", value="FULL_OUTBOUND"),
    ]
    value, _ = resolve_config(entries, category="security",
                              key="network_policy")
    assert value == "INTERNAL_ONLY"


def test_security_can_be_tightened():
    entries = [
        ConfigEntry(scope="PLATFORM", scope_id="", category="security",
                    key="network_policy", value="ALLOWLIST"),
        ConfigEntry(scope="ENVIRONMENT", scope_id="prod",
                    category="security", key="network_policy",
                    value="NO_NETWORK"),
    ]
    value, _ = resolve_config(entries, category="security",
                              key="network_policy")
    assert value == "NO_NETWORK"


def test_resolve_all_groups():
    entries = [ConfigEntry(scope="PLATFORM", scope_id="", category="runtime",
                           key="timeout", value=60)]
    assert resolve_all(entries) == {"runtime": {"timeout": 60}}


def test_change_preview_blocks_relaxation():
    preview = preview_change("INTERNAL_ONLY", "FULL_OUTBOUND",
                             key="network_policy", category="security")
    assert preview["blocked"] and preview["relaxes_security"]
    preview = preview_change("ALLOWLIST", "NO_NETWORK",
                             key="network_policy", category="security")
    assert not preview["blocked"]


def test_policy_resolver_first_deny_wins():
    resolver = PolicyResolver([
        ("rbac", lambda ctx: PolicyDecision.allow("member")),
        ("quota", lambda ctx: PolicyDecision.deny("quota exceeded")),
    ])
    decision = resolver.decide({})
    assert not decision.allowed and decision.policy_id == "quota"


def test_policy_resolver_fail_closed_on_error():
    resolver = PolicyResolver([("boom", lambda ctx: 1 / 0)])
    decision = resolver.decide({})
    assert not decision.allowed


def test_policy_resolver_empty_fail_closed():
    assert not PolicyResolver([]).decide({}).allowed
    assert PolicyResolver([], fail_closed=False).decide({}).allowed


def test_environment_mixing_blocked():
    assert not environment_allows(resource_env="PRODUCTION",
                                  target_env="DEVELOPMENT").allowed
    assert environment_allows(resource_env="STAGING",
                              target_env="STAGING").allowed


def test_policy_decision_never_leaks_secrets():
    decision = PolicyDecision.allow("ok", metadata={"api_key": "sk-live-123",
                                                    "note": "fine"})
    body = decision.to_dict()
    assert body["metadata"]["api_key"] == "[REDACTED]"
    assert body["metadata"]["note"] == "fine"
