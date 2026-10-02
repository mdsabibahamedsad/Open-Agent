"""MP27: SAML foundation (§8-9). IdP/SP metadata, SSO, and full
assertion validation (timestamps, audience, recipient, replay, NameID +
attribute mapping). XML signature verification is delegated to a
maintained library via an injectable verifier — signature checks are
NEVER skipped in production, and no XML crypto is implemented here.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from openagent.identity.providers import (
    AuthRequest, AuthResult, IdentityProvider, ProvisioningResult,
)

NS = {"md": "urn:oasis:names:tc:SAML:2.0:metadata",
      "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
      "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
      "ds": "http://www.w3.org/2000/09/xmldsig#"}


class SamlError(Exception):
    pass


@dataclass
class SamlConfig:
    entity_id: str  # our SP entity id
    acs_url: str
    idp_entity_id: str
    sso_url: str
    audience: str = ""
    clock_skew_seconds: int = 120
    require_signed_assertion: bool = True
    nameid_mapping: str = "email"  # email|persistent|transient
    attribute_mapping: dict[str, str] = field(default_factory=dict)
    # Injectable signature verifier: fn(xml_string, idp_cert_pem) -> bool.
    # Production MUST supply one backed by a maintained SAML library.
    signature_verifier: Optional[Callable[[str, str], bool]] = None
    idp_cert_pem: str = ""

    def validate(self) -> tuple[bool, str]:
        if not self.entity_id or not self.acs_url:
            return False, "SP entity_id and acs_url are required"
        if not self.idp_entity_id or not self.sso_url:
            return False, "IdP entity_id and sso_url are required"
        if not self.sso_url.startswith("https://") and "localhost" not in self.sso_url:
            return False, "SSO URL must be https"
        return True, "ok"


def parse_idp_metadata(metadata_xml: str) -> dict[str, Any]:
    """Extract entity id, SSO URL, and certs from IdP metadata."""
    try:
        root = ET.fromstring(metadata_xml)
    except ET.ParseError as exc:
        raise SamlError("invalid IdP metadata XML") from exc
    entity_id = root.attrib.get("entityID", "")
    if not entity_id:
        raise SamlError("IdP metadata missing entityID")
    sso = ""
    for binding in root.findall(".//md:SingleSignOnService", NS):
        if "HTTP-Redirect" in binding.attrib.get("Binding", ""):
            sso = binding.attrib.get("Location", "")
            break
    sso = sso or (root.find(".//md:SingleSignOnService",
                            NS).attrib.get("Location", "")
                  if root.find(".//md:SingleSignOnService", NS) is not None
                  else "")
    certs = [ (node.text or "").strip()
              for node in root.findall(".//ds:X509Certificate", NS)]
    if not sso:
        raise SamlError("IdP metadata missing SingleSignOnService")
    return {"entity_id": entity_id, "sso_url": sso, "certs": certs}


def sp_metadata(entity_id: str, acs_url: str) -> str:
    return (f'<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" '
            f'entityID="{entity_id}"><SPSSODescriptor protocolSupportEnumeration='
            f'"urn:oasis:names:tc:SAML:2.0:protocol"><AssertionConsumerService '
            f'Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
            f'Location="{acs_url}" index="1"/></SPSSODescriptor></EntityDescriptor>')


def _parse_time(value: str) -> float:
    from datetime import datetime, timezone
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError as exc:
        raise SamlError(f"invalid SAML timestamp {value}") from exc


class ReplayCache:
    """Assertion-ID replay protection (single-use assertions)."""

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    def check_and_store(self, assertion_id: str, expires_at: float,
                        now: Optional[float] = None) -> None:
        moment = now if now is not None else time.time()
        self._seen = {k: v for k, v in self._seen.items() if v > moment}
        if assertion_id in self._seen:
            raise SamlError("assertion replay detected")
        self._seen[assertion_id] = expires_at


def validate_response(response_xml: str, *, config: SamlConfig,
                      expected_request_id: str = "",
                      replay: Optional[ReplayCache] = None,
                      now: Optional[float] = None) -> dict[str, Any]:
    """Validate a SAML Response. Raises SamlError on any failure."""
    moment = now if now is not None else time.time()
    try:
        root = ET.fromstring(response_xml)
    except ET.ParseError as exc:
        raise SamlError("malformed SAML response") from exc

    if root.tag != "{urn:oasis:names:tc:SAML:2.0:protocol}Response":
        raise SamlError("not a SAML Response")
    status = root.find("samlp:Status/samlp:StatusCode", NS)
    if status is None or status.attrib.get("Value", "") != \
            "urn:oasis:names:tc:SAML:2.0:status:Success":
        raise SamlError("SAML response status is not Success")

    issuer = root.find("saml:Issuer", NS)
    if issuer is None or (issuer.text or "").strip() != config.idp_entity_id:
        raise SamlError("invalid response issuer")

    if expected_request_id:
        in_response_to = root.attrib.get("InResponseTo", "")
        if in_response_to != expected_request_id:
            raise SamlError("InResponseTo mismatch (possible injection)")

    assertion = root.find("saml:Assertion", NS)
    if assertion is None:
        raise SamlError("missing assertion")
    assertion_id = assertion.attrib.get("ID", "")
    if not assertion_id:
        raise SamlError("assertion missing ID")

    # Signature: verified by maintained lib; absence is fatal in prod.
    has_signature = (assertion.find("ds:Signature", NS) is not None
                     or root.find("ds:Signature", NS) is not None)
    if config.require_signed_assertion:
        if not has_signature:
            raise SamlError("unsigned assertion rejected")
        if config.signature_verifier is None:
            raise SamlError(
                "no SAML signature verifier configured — refusing to "
                "trust the assertion (configure a maintained SAML library)")
        if not config.idp_cert_pem:
            raise SamlError("no IdP certificate configured")
        if not config.signature_verifier(response_xml, config.idp_cert_pem):
            raise SamlError("invalid assertion signature")

    conditions = assertion.find("saml:Conditions", NS)
    if conditions is None:
        raise SamlError("assertion missing Conditions")
    skew = config.clock_skew_seconds
    nb = conditions.attrib.get("NotBefore")
    noa = conditions.attrib.get("NotOnOrAfter")
    if nb and moment < _parse_time(nb) - skew:
        raise SamlError("assertion not yet valid")
    if noa and moment >= _parse_time(noa) + skew:
        raise SamlError("assertion expired")

    audience_ok = False
    expected_aud = config.audience or config.entity_id
    for restriction in conditions.findall("saml:AudienceRestriction", NS):
        for aud in restriction.findall("saml:Audience", NS):
            if (aud.text or "").strip() == expected_aud:
                audience_ok = True
    if not audience_ok:
        raise SamlError("invalid audience")

    recipient_ok = False
    for confirm in assertion.findall(
            "saml:Subject/saml:SubjectConfirmation", NS):
        data = confirm.find("saml:SubjectConfirmationData", NS)
        if data is None:
            continue
        if data.attrib.get("Recipient", "") not in ("", config.acs_url):
            raise SamlError("invalid recipient")
        ron = data.attrib.get("NotOnOrAfter")
        if ron and moment >= _parse_time(ron) + skew:
            raise SamlError("subject confirmation expired")
        if expected_request_id and data.attrib.get("InResponseTo", "") \
                and data.attrib.get("InResponseTo") != expected_request_id:
            raise SamlError("subject InResponseTo mismatch")
        recipient_ok = True
    if not recipient_ok:
        raise SamlError("no valid subject confirmation")

    if replay is not None:
        expiry = _parse_time(noa) if noa else moment + 300
        replay.check_and_store(assertion_id, expiry, now=moment)

    nameid = assertion.find("saml:Subject/saml:NameID", NS)
    nameid_value = (nameid.text or "").strip() if nameid is not None else ""
    attributes: dict[str, list[str]] = {}
    for statement in assertion.findall("saml:AttributeStatement", NS):
        for attr in statement.findall("saml:Attribute", NS):
            name = attr.attrib.get("Name", "")
            values = [(v.text or "") for v in
                      attr.findall("saml:AttributeValue", NS)]
            attributes[name] = values

    mapped: dict[str, str] = {}
    for saml_attr, local in config.attribute_mapping.items():
        values = attributes.get(saml_attr, [])
        if values:
            mapped[local] = values[0]
    return {"nameid": nameid_value,
            "nameid_format": nameid.attrib.get("Format", "")
            if nameid is not None else "",
            "attributes": attributes, "mapped": mapped,
            "assertion_id": assertion_id}


class SamlIdentityProvider(IdentityProvider):
    provider_type = "saml"

    def __init__(self, config: SamlConfig,
                 replay: Optional[ReplayCache] = None) -> None:
        ok, reason = config.validate()
        if not ok:
            raise ValueError(reason)
        self.config = config
        self.replay = replay or ReplayCache()

    async def authenticate(self, request: AuthRequest) -> str:
        from urllib.parse import urlencode
        params = {"SAMLRequest": "placeholder-deflated",
                  "RelayState": request.organization_id}
        return f"{self.config.sso_url}?{urlencode(params)}"

    async def validate_assertion(self, payload: dict[str, Any],
                                 context: dict[str, Any]) -> AuthResult:
        result = validate_response(
            str(payload.get("response_xml", "")),
            config=self.config,
            expected_request_id=str(context.get("request_id", "")),
            replay=self.replay)
        mapped = result["mapped"]
        email = mapped.get("email", "")
        if self.config.nameid_mapping == "email" and "@" in result["nameid"]:
            email = email or result["nameid"]
        groups = result["attributes"].get(
            mapped.get("groups_attr", "groups"), [])
        if isinstance(groups, str):
            groups = [groups]
        return AuthResult(subject=result["nameid"], email=email,
                          email_verified=bool(email),
                          display_name=mapped.get("display_name", ""),
                          groups=list(groups), attributes=mapped,
                          auth_strength="AAL1", raw_claims={})

    async def provision_user(self, result: AuthResult,
                             context: dict[str, Any]) -> ProvisioningResult:
        return ProvisioningResult(created=True, user_id=result.subject,
                                  detail="jit provision candidate")

    async def deprovision_user(self, subject: str,
                               context: dict[str, Any]) -> bool:
        return True

    async def get_groups(self, subject: str,
                         context: dict[str, Any]) -> list[str]:
        return list(context.get("groups", []) or [])
