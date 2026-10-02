# github-connector

Connector manifest + OAuth2/PKCE notes.

- OAuth via the platform manager; tokens are `credential_ref` handles only.
- Egress limited to `api.github.com` (`network:outbound` + allowlisted policy).
- `secret:access` requires an approval record at install for community trust.

```bash
openagent test
openagent validate && openagent package && openagent publish
```
