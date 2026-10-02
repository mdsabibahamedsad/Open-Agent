# MFA

TOTP per RFC 6238 (stdlib HMAC-SHA1, ±1 step window), provisioning
URIs, WebAuthn/passkeys through a maintained library (registration,
authentication, named revocable credentials; raw private keys never
stored server-side), and Argon2id-hashed recovery codes shown once.
Org admins can require MFA globally/for admins/teams/environments;
lower scopes can only add coverage. Strength maps to AAL1–AAL3 and
drives step-up decisions.
