# SAML

IdP metadata import (entityID, Redirect SSO URL, certs), SP metadata
export, and Response validation: Success status, issuer match,
InResponseTo binding, mandatory Signature verified by an injected
maintained-library verifier (absence or missing verifier = reject in
production), Conditions window, audience restriction, recipient +
subject-confirmation expiry, assertion-ID replay cache, NameID +
attribute mapping. No XML crypto is implemented here.
