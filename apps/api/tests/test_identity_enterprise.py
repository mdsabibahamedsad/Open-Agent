"""MP27 unit: SSO config, domains, JIT, group mapping, SCIM."""

import pytest

from openagent.identity.scim import (
    ScimCredential, ScimRateLimiter, apply_filter, apply_patch,
    paginate, parse_filter, validate_scim_group, validate_scim_user,
)
from openagent.identity.sso import (
    DomainRegistry, GroupMapping, SsoConfiguration, jit_plan,
    resolve_memberships, sso_test_preview,
)


def test_sso_config_validation():
    ok, _ = SsoConfiguration(
        organization_id="o1", provider_type="oidc",
        issuer="https://idp.example.com", client_id="c1",
        client_secret_ref="vault://sso/o1").validate()
    assert ok
    ok, reason = SsoConfiguration(
        organization_id="o1", provider_type="oidc", issuer="",
        client_id="c1").validate()
    assert not ok
    ok, _ = SsoConfiguration(
        organization_id="o1", provider_type="saml",
        issuer="https://idp.example.com").validate()
    assert not ok  # metadata required
    config = SsoConfiguration(organization_id="o1",
                              provider_type="oidc",
                              issuer="https://idp.example.com",
                              client_id="c1", status="DRAFT")
    assert not config.can_enforce()[0]


def test_domain_claim_verify_route():
    registry = DomainRegistry()
    claim = registry.claim("Example.COM", "org-a")
    assert claim.domain == "example.com" and claim.status == "PENDING"
    with pytest.raises(ValueError):
        registry.verify("example.com", "wrong")
    registry.verify("example.com", claim.challenge)
    assert registry.route("user@example.com").organization_id == "org-a"
    assert registry.route("user@other.com") is None
    assert registry.route("not-an-email") is None
    # Second org cannot claim a verified domain.
    with pytest.raises(ValueError):
        registry.claim("example.com", "org-b")


def test_jit_never_auto_owner():
    plan = jit_plan(user_exists=False, organization_id="o1",
                    requested_role="owner")
    assert plan.role == "member" and plan.create_user
    plan = jit_plan(user_exists=True, organization_id="o1",
                    requested_role="owner", allow_owner_via_claim=True)
    assert plan.role == "owner"
    plan = jit_plan(user_exists=False, organization_id="o1",
                    requested_role="nonsense")
    assert plan.role == "member"


def test_group_mapping_safety():
    bad = GroupMapping(external_group="Everyone", role="platform_owner")
    assert not bad.validate()[0]
    good = GroupMapping(external_group="Engineering", team="devs",
                        role="developer")
    assert good.validate()[0]
    grants, warnings = resolve_memberships(
        ["Engineering", "Execs"],
        [good, GroupMapping(external_group="Execs", role="owner")])
    assert [g.external_group for g in grants] == ["Engineering", "Execs"]
    assert any("owner" in w for w in warnings)


def test_sso_test_preview_changes_nothing():
    preview = sso_test_preview(email="a@example.com", groups=["Eng"],
                               mappings=[GroupMapping(
                                   external_group="Eng", team="devs",
                                   role="developer")],
                               user_exists=False,
                               organization_id="o1")
    assert preview["applied"] is False
    assert preview["proposed_role"] == "developer"
    assert preview["would_create_user"] is True


def test_scim_filter_subset():
    users = [{"userName": "amy", "active": True,
              "emails": [{"value": "amy@example.com"}]},
             {"userName": "bob", "active": False, "emails": []}]
    assert len(apply_filter(users, parse_filter('userName eq "amy"'))) == 1
    assert len(apply_filter(users, parse_filter("active eq true"))) == 1
    assert len(apply_filter(users, parse_filter("emails co example.com"))) == 1
    with pytest.raises(Exception):
        parse_filter("userName gt 5")  # unsupported operator
    with pytest.raises(Exception):
        parse_filter("is_admin eq true")  # unfilterable attribute


def test_scim_pagination_caps():
    page = paginate(list(range(1000)), start_index=1, count=9999)
    assert page["itemsPerPage"] == 500  # never dump a directory


def test_scim_patch_closed_vocabulary():
    target = {"userName": "amy", "active": True}
    updated = apply_patch(target, [{"op": "replace", "path": "displayName",
                                     "value": "Amy"}])
    assert updated["displayName"] == "Amy"
    with pytest.raises(Exception):
        apply_patch(target, [{"op": "replace", "path": "roles",
                              "value": ["admin"]}])  # never permissions
    with pytest.raises(Exception):
        apply_patch(target, [{"op": "frob", "path": "active"}])


def test_scim_validation_rejects_privilege_attrs():
    with pytest.raises(Exception):
        validate_scim_user({"userName": "x", "is_admin": True})
    with pytest.raises(Exception):
        validate_scim_user({"userName": ""})
    clean = validate_scim_user({"userName": "amy"})
    assert clean["active"] is True
    with pytest.raises(Exception):
        validate_scim_group({"displayName": ""})
    with pytest.raises(Exception):
        validate_scim_group({"displayName": "g", "members": "nope"})


def test_scim_rate_limiter_and_credential():
    limiter = ScimRateLimiter()
    ok, _ = limiter.check("cred-1", "bulk")
    assert ok
    blocked = False
    for _ in range(30):
        ok, _ = limiter.check("cred-1", "bulk")
        if not ok:
            blocked = True
            break
    assert blocked  # 10/minute bulk bucket trips
    credential = ScimCredential(credential_id="c", organization_id="o",
                                token_hash="h", expires_at=0.0)
    assert credential.usable()[0]  # no expiry = long-lived but revocable
    credential.revoked = True
    assert not credential.usable()[0]
