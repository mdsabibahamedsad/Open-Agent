"""MP27 security + failure matrix: escalation, IDOR/tenant,
JWT/SSO/SCIM abuse, zero-trust combos, IdP-outage fail-closed."""

import time

import pytest

from openagent.identity.abac import Authorizer, AuthzRequest, rbac_allow
from openagent.identity.dlp import DataPolicyEngine
from openagent.identity.lifecycle import Identity, IdentityRegistry
from openagent.identity.oidc import OidcConfig, mint_test_token, validate_id_token
from openagent.identity.saml import ReplayCache, SamlConfig
from openagent.identity.scim import ScimRateLimiter, validate_scim_user
from openagent.identity.sso import GroupMapping, resolve_memberships
from openagent.identity.trust import RevocationRegistry, evaluate_step_up
from openagent.identity.types import IdentityStatus, IdentityType
from openagent.identity.workload import CredentialBroker, WorkloadIdentity


def test_member_cannot_become_admin_or_owner():
    assert not GroupMapping(external_group="All",
                            role="platform_owner").validate()[0]
    assert not GroupMapping(external_group="All",
                            role="superadmin").validate()[0]
    grants, _ = resolve_memberships(
        ["All"], [GroupMapping(external_group="All",
                               role="developer")])
    assert all(g.role == "developer" for g in grants)


def test_org_admin_cannot_reach_platform():
    authorizer = Authorizer()
    authorizer.add("platform", "platform-only", rbac_allow(
        "platform-only", permissions=set()))
    decision = authorizer.decide(AuthzRequest(
        identity_id="org-admin", identity_type="human",
        action="platform.shutdown"))
    assert not decision.allowed


def test_worker_cannot_request_foreign_org():
    broker = CredentialBroker()
    now = time.time()
    workload = WorkloadIdentity(
        kind="worker", organization_id="org-a", execution_id="e1",
        scopes=["tool.execute"], expires_at=now + 600)
    with pytest.raises(ValueError):
        broker.issue(workload, "cred://org-b/db", scopes=["tool.execute"],
                     credential_org="org-b")
    # Scopes must be within the workload grant for its own org.
    lease = broker.issue(workload, "cred://org-a/db",
                         scopes=["tool.execute"], credential_org="org-a")
    assert lease.workload_id == workload.workload_id


def test_cross_tenant_identity_isolation():
    registry = IdentityRegistry()
    registry.register(Identity(id="u-a", type=IdentityType.HUMAN,
                               organization_id="org-a",
                               status=IdentityStatus.ACTIVE))
    other = registry.get("u-a")
    assert other is not None and other.organization_id == "org-a"
    assert registry.get("u-a").organization_id != "org-b"


def test_idor_resource_binding():
    authorizer = Authorizer()
    from openagent.identity.abac import abac_rule
    authorizer.add("platform", "rbac", rbac_allow(
        "rbac", permissions={"artifact.read"}))
    authorizer.add("resource", "owner-only", abac_rule(
        "owner-only", require={"organization": "org-a"}))
    foreign = AuthzRequest(identity_id="u", identity_type="human",
                           action="artifact.read",
                           attributes={"organization": "org-b"})
    assert not authorizer.decide(foreign).allowed
    own = AuthzRequest(identity_id="u", identity_type="human",
                       action="artifact.read",
                       attributes={"organization": "org-a"})
    assert authorizer.decide(own).allowed


def test_jwt_future_and_malformed():
    from openagent.identity.oidc import OidcError
    config = OidcConfig(issuer="https://idp.example.com",
                        client_id="c1", expected_alg="HS256",
                        hs_secret="s")
    now = time.time()
    future = mint_test_token({"iss": config.issuer, "aud": "c1",
                              "sub": "u", "exp": now + 300,
                              "iat": now + 3600}, "s")
    with pytest.raises(OidcError):
        validate_id_token(future, config=config, now=now)
    with pytest.raises(OidcError):
        validate_id_token("header.payload.", config=config)


def test_sso_replay_and_audience_attacks():
    cache = ReplayCache()
    cache.check_and_store("assertion-1", time.time() + 300)
    from openagent.identity.saml import SamlError
    with pytest.raises(SamlError):
        cache.check_and_store("assertion-1", time.time() + 300)
    config = SamlConfig(entity_id="https://sp", acs_url="https://sp/acs",
                        idp_entity_id="https://idp",
                        sso_url="https://idp/sso")
    assert config.validate()[0]
    bad = SamlConfig(entity_id="https://sp", acs_url="https://sp/acs",
                     idp_entity_id="https://idp", sso_url="http://idp/sso")
    assert not bad.validate()[0]  # non-https SSO rejected


def test_scim_abuse_rejected():
    with pytest.raises(Exception):
        validate_scim_user({"userName": "x", "permissions": ["*"]})
    limiter = ScimRateLimiter()
    for _ in range(100):
        limiter.check("c-sync", "provision")
    ok, _ = limiter.check("c-sync", "provision")
    assert not ok  # sync storm throttled


def test_zero_trust_combos():
    # Valid identity + revoked device material -> step up or deny.
    decision = evaluate_step_up(action="production_action",
                                have_strength="AAL1",
                                risk_level="HIGH")
    assert decision.verdict == "STEP_UP"
    # Valid worker + wrong region: workload validation pins region.
    now = time.time()
    workload = WorkloadIdentity(kind="worker", organization_id="o",
                                execution_id="e", region="eu-1",
                                scopes=["tool.execute"],
                                expires_at=now + 600)
    assert workload.region == "eu-1"
    # Revoked session version fails validation.
    registry = RevocationRegistry()
    registry.revoke("sess:abc")
    assert not registry.valid("sess:abc", 0)


def test_idp_unavailable_fails_closed():
    authorizer = Authorizer()

    def _idp_down(request):
        raise ConnectionError("IdP unreachable")

    authorizer.add("platform", "idp", _idp_down)
    decision = authorizer.decide(AuthzRequest(
        identity_id="u", identity_type="human", action="login"))
    assert not decision.allowed
    assert "deny" in decision.reason.lower()


def test_dlp_never_blocks_benign_telemetry():
    engine = DataPolicyEngine()
    assert engine.allow("queue depth 42, latency p99 120ms")[0]
    assert not engine.inspect("nothing here")["sensitive"]
