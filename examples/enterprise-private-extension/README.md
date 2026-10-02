# enterprise-private-extension

Private org extension: SSO-gated install (group `acme-platform`), RBAC-scoped
invoke, secret-ref credentials, allowlisted egress. Never published publicly.

```bash
openagent validate && openagent package
openagent publish --registry private && openagent deploy --env production
```
