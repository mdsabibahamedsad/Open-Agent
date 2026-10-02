"""MP27 unit: identity lifecycle, OIDC validation, SAML validation."""

import time

import pytest

from openagent.identity.lifecycle import Identity, IdentityRegistry
from openagent.identity.oidc import (
    OidcConfig, build_login, mint_test_token, parse_discovery_document,
    validate_id_token,
)
from openagent.identity.saml import (
    ReplayCache, SamlConfig, parse_idp_metadata, sp_metadata,
    validate_response,
)
from openagent.identity.types import IdentityStatus, IdentityType


def test_identity_validation():
    ok, _ = Identity(id="a", type=IdentityType.HUMAN,
                     organization_id="o1").validate()
    assert ok
    ok, reason = Identity(id="a", type="starship",
                          organization_id="o1").validate()
    assert not ok
    ok, reason = Identity(id="a", type=IdentityType.HUMAN).validate()
    assert not ok and "organization_id" in reason
    # Platform identity needs no org.
    ok, _ = Identity(id="p", type=IdentityType.PLATFORM).validate()
    assert ok


def test_identity_lifecycle_validated():
    registry = IdentityRegistry()
    identity = registry.register(Identity(id="u1", type=IdentityType.HUMAN,
                                          organization_id="o1",
                                          status=IdentityStatus.INVITED))
    assert identity.usable()[0] is False
    registry.transition("u1", IdentityStatus.ACTIVE)
    assert registry.get("u1").usable()[0] is True
    with pytest.raises(ValueError):
        registry.transition("u1", IdentityStatus.INVITED)  # no way back


def test_deactivation_preserves_history():
    registry = IdentityRegistry()
    registry.register(Identity(id="u2", type=IdentityType.HUMAN,
                               organization_id="o1",
                               status=IdentityStatus.ACTIVE))
    tombstone = registry.deactivate_preserve("u2")
    assert tombstone.status in ("DISABLED", "REVOKED", "SUSPENDED")
    assert registry.get("u2") is not None  # record preserved


def _oidc_config() -> OidcConfig:
    return OidcConfig(issuer="https://idp.example.com",
                      client_id="client-1",
                      redirect_uri="https://app.example.com/cb",
                      expected_alg="HS256", hs_secret="test-secret")


def test_oidc_happy_path():
    config = _oidc_config()
    now = time.time()
    token = mint_test_token({"iss": config.issuer, "aud": "client-1",
                             "sub": "user-1", "exp": now + 300,
                             "iat": now, "email": "a@b.co"}, "test-secret")
    claims = validate_id_token(token, config=config, now=now)
    assert claims["sub"] == "user-1"


def test_oidc_rejects_wrong_issuer_audience_expiry_signature():
    config = _oidc_config()
    now = time.time()
    base = {"iss": config.issuer, "aud": "client-1", "sub": "u",
            "exp": now + 300, "iat": now}
    from openagent.identity.oidc import OidcError
    tampered = mint_test_token({**base, "iss": "https://evil.example.com"},
                               "test-secret")
    with pytest.raises(OidcError):
        validate_id_token(tampered, config=config, now=now)
    wrong_aud = mint_test_token({**base, "aud": "someone-else"},
                                "test-secret")
    with pytest.raises(OidcError):
        validate_id_token(wrong_aud, config=config, now=now)
    expired = mint_test_token({**base, "exp": now - 500}, "test-secret")
    with pytest.raises(OidcError):
        validate_id_token(expired, config=config, now=now)
    forged = mint_test_token(base, "wrong-secret")
    with pytest.raises(OidcError):
        validate_id_token(forged, config=config, now=now)


def test_oidc_rejects_none_alg_and_confusion():
    from openagent.identity.oidc import OidcError, _b64url_encode
    import json
    header = _b64url_encode(json.dumps({"alg": "none"}).encode())
    payload = _b64url_encode(json.dumps({"sub": "u"}).encode())
    with pytest.raises(OidcError):
        validate_id_token(f"{header}.{payload}.", config=_oidc_config())
    with pytest.raises(OidcError):
        validate_id_token("not.a.jwt", config=_oidc_config())


def test_oidc_discovery_and_login_shape():
    doc = {"issuer": "https://idp.example.com",
           "authorization_endpoint": "https://idp.example.com/auth",
           "token_endpoint": "https://idp.example.com/token",
           "userinfo_endpoint": "https://idp.example.com/me",
           "jwks_uri": "https://idp.example.com/keys"}
    endpoints = parse_discovery_document(doc, "https://idp.example.com")
    assert endpoints["token_endpoint"].startswith("https://")
    from openagent.identity.oidc import OidcError
    with pytest.raises(OidcError):
        parse_discovery_document({**doc, "issuer": "https://evil.test"},
                                 "https://idp.example.com")
    url, state, nonce, verifier = build_login(
        _oidc_config(), state_secret="s3cret", organization_id="o1")
    assert url.startswith("https://") and state and nonce and verifier


SAML_RESPONSE = """<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" ID="r1" InResponseTo="req-1" Version="2.0" IssueInstant="2026-01-01T00:00:00Z"><saml:Issuer xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">https://idp.example.com</saml:Issuer><samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status><saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="a1" IssueInstant="2026-01-01T00:00:00Z"><saml:Issuer>https://idp.example.com</saml:Issuer><ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#"><x/></ds:Signature><saml:Subject><saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">user@example.com</saml:NameID><saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer"><saml:SubjectConfirmationData Recipient="https://sp.example.com/acs" InResponseTo="req-1" NotOnOrAfter="2026-01-01T00:10:00Z"/></saml:SubjectConfirmation></saml:Subject><saml:Conditions NotBefore="2025-12-31T23:55:00Z" NotOnOrAfter="2026-01-01T00:10:00Z"><saml:AudienceRestriction><saml:Audience>https://sp.example.com</saml:Audience></saml:AudienceRestriction></saml:Conditions><saml:AttributeStatement><saml:Attribute Name="email"><saml:AttributeValue>user@example.com</saml:AttributeValue></saml:Attribute><saml:Attribute Name="groups"><saml:AttributeValue>eng</saml:AttributeValue></saml:Attribute></saml:AttributeStatement></saml:Assertion></samlp:Response>"""


def _saml_config() -> SamlConfig:
    return SamlConfig(
        entity_id="https://sp.example.com",
        acs_url="https://sp.example.com/acs",
        idp_entity_id="https://idp.example.com",
        sso_url="https://idp.example.com/sso",
        audience="https://sp.example.com",
        signature_verifier=lambda xml, cert: True,
        idp_cert_pem="CERT")


def _saml_time() -> float:
    from datetime import datetime, timezone
    return datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc).timestamp()


def test_saml_happy_path():
    result = validate_response(
        SAML_RESPONSE, config=_saml_config(), expected_request_id="req-1",
        replay=ReplayCache(), now=_saml_time())
    assert result["nameid"] == "user@example.com"
    assert result["mapped"] == {}


def test_saml_rejects_replay_expired_audience_recipient():
    from openagent.identity.saml import SamlError
    replay = ReplayCache()
    validate_response(SAML_RESPONSE, config=_saml_config(),
                      expected_request_id="req-1", replay=replay,
                      now=_saml_time())
    with pytest.raises(SamlError):  # replay
        validate_response(SAML_RESPONSE, config=_saml_config(),
                          expected_request_id="req-1", replay=replay,
                          now=_saml_time())
    with pytest.raises(SamlError):  # expired
        validate_response(SAML_RESPONSE, config=_saml_config(),
                          expected_request_id="req-1", now=_saml_time() + 3600)
    bad_aud = _saml_config()
    bad_aud.audience = "https://someone-else.example.com"
    with pytest.raises(SamlError):
        validate_response(SAML_RESPONSE, config=bad_aud,
                          expected_request_id="req-1", now=_saml_time())
    with pytest.raises(SamlError):  # wrong request binding
        validate_response(SAML_RESPONSE, config=_saml_config(),
                          expected_request_id="req-OTHER",
                          now=_saml_time())


def test_saml_never_skips_signatures():
    from openagent.identity.saml import SamlError
    unsigned = SAML_RESPONSE.replace(
        '<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#"><x/></ds:Signature>',
        '')
    with pytest.raises(SamlError):
        validate_response(unsigned, config=_saml_config(),
                          expected_request_id="req-1", now=_saml_time())
    no_verifier = _saml_config()
    no_verifier.signature_verifier = None
    with pytest.raises(SamlError):
        validate_response(SAML_RESPONSE, config=no_verifier,
                          expected_request_id="req-1", now=_saml_time())


def test_saml_metadata_and_sp():
    xml = (
        '<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" '
        'entityID="https://idp.example.com"><md:IDPSSODescriptor>'
        '<md:SingleSignOnService '
        'Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" '
        'Location="https://idp.example.com/sso"/>'
        '<md:KeyDescriptor><ds:KeyInfo '
        'xmlns:ds="http://www.w3.org/2000/09/xmldsig#"><ds:X509Data>'
        '<ds:X509Certificate>MIIB</ds:X509Certificate>'
        '</ds:X509Data></ds:KeyInfo></md:KeyDescriptor>'
        '</md:IDPSSODescriptor></md:EntityDescriptor>')
    parsed = parse_idp_metadata(xml)
    assert parsed["entity_id"] == "https://idp.example.com"
    assert parsed["sso_url"].startswith("https://")
    assert "MIIB" in parsed["certs"]
    assert "AssertionConsumerService" in sp_metadata("https://sp", "https://sp/acs")
