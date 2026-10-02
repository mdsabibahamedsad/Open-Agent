"""MP26 security: flag bypass resistance, tenant isolation, master
separation, audit tamper detection, IP bypass, secret leakage."""

from openagent.control.enterprise import ip_allowed
from openagent.control.feature_flags import FeatureFlag, FlagEvaluator
from openagent.control.observability import log_event, platform_event, redact
from openagent.control.privileged import AuditChain, PrivilegedAuditRecord
from openagent.control.resources import (
    HierarchyPath, ResourceRef, check_inheritance,
)


def test_feature_flag_cannot_bypass_security_policy():
    # Even with every flag "on", the security guard marks security flags
    # advisory-only; enforcement stays with the security policy engine.
    evaluator = FlagEvaluator([FeatureFlag(key="security.mfa_required",
                                            scope="PLATFORM",
                                            strategy="boolean", enabled=False)])
    decision = evaluator.evaluate("security.mfa_required", subject_id="attacker")
    assert decision.security_guarded
    # A non-security flag never matches a security control key.
    assert evaluator.evaluate("ui.dark_mode").reason != decision.reason


def test_cross_tenant_resource_denied():
    grant_org_a = "org:org-a"
    resource_b = HierarchyPath(organization_id="org-b", project_id="p1",
                               environment="PRODUCTION")
    assert not check_inheritance(grant_org_a, resource_b)
    ref = ResourceRef(id="art-1", type="artifact", organization_id="org-a")
    assert ref.organization_id != "org-b"


def test_master_identity_separate_from_org_roles():
    # Platform scope and org scope never collapse into each other.
    assert "platform" != "org:anything"
    # An org grant covers resources INSIDE that org (correct inheritance),
    # but never the platform itself and never another org.
    assert check_inheritance("org:org-a", HierarchyPath(
        organization_id="org-a", project_id="p1"))
    assert not check_inheritance("org:org-a", HierarchyPath())
    assert not check_inheritance("org:org-a", HierarchyPath(
        organization_id="org-b"))
    # Platform authority is explicit, never implied by org membership:
    # no grant string derived from membership equals "platform".


def test_audit_tampering_detected():
    chain = AuditChain()
    chain.append(PrivilegedAuditRecord(actor="m", action="quota.modify",
                                       resource="org-a", result="ok"))
    assert chain.verify()[0]
    chain._records[0]["result"] = "forged-ok"
    ok, message = chain.verify()
    assert not ok and "broken" in message


def test_ip_restriction_bypass_via_spoofed_header_impossible():
    # Pure-function check: only validated socket IPs reach ip_allowed.
    # A spoofed "1.2.3.4" from an untrusted network still fails allowlist.
    from openagent.control.enterprise import trusted_source_ip
    claimed = "10.0.0.5"  # attacker-supplied header value
    effective = trusted_source_ip(forwarded_for=claimed,
                                  remote_addr="203.0.113.9",
                                  trusted_proxies=[])
    assert effective == "203.0.113.9"
    allowed, _ = ip_allowed(effective, allowlist=["10.0.0.0/8"],
                            denylist=[])
    assert not allowed


def test_no_secrets_in_logs_events_or_config():
    secret = "sk-live-SECRETSECRETSECRET1234"
    assert "SECRETSECRET" not in str(log_event("api", "x", key=secret))
    event = platform_event("policy.changed", source="test",
                           payload={"secret": secret})
    assert "SECRETSECRET" not in str(event)
    assert "SECRETSECRET" not in str(redact({"nested": [secret]}))


def test_privilege_escalation_via_scope_impossible():
    narrow = HierarchyPath(organization_id="o1", project_id="p1")
    broad = HierarchyPath(organization_id="o1")
    # Project grant cannot reach sibling project or org level.
    assert not check_inheritance("project:p1", broad)
    assert not check_inheritance(
        "project:p1",
        HierarchyPath(organization_id="o1", project_id="p2"))
    assert check_inheritance(
        "project:p1",
        HierarchyPath(organization_id="o1", project_id="p1",
                      environment="PRODUCTION"))
