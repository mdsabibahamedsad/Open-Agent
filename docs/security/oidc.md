# OIDC

Discovery (issuer-pinned, https endpoints), authorization code flow
with PKCE S256, signed state (CSRF), nonce binding, and full ID-token
validation: pinned algorithm (confusion-resistant, `none` rejected),
signature (RS256 via maintained JWT lib, HS256 via HMAC for tests/
local IdPs), issuer, audience, expiry + clock skew, future-iat guard,
subject presence. Raw claims never leave the validation boundary.
