"""Sandbox API contract tests: route registration (no database required)."""

from openagent.api.v1.sandboxes import (
    exec_router as sandbox_executions_router,
)
from openagent.api.v1.sandboxes import (
    profiles_router as sandbox_profiles_router,
)
from openagent.api.v1.sandboxes import (
    router as sandboxes_router,
)


def _routes(router):
    out = {}
    for r in router.routes:
        methods = tuple(sorted(getattr(r, "methods", set()) or set()))
        out.setdefault(getattr(r, "path", ""), set()).update(methods)
    return out


REQUIRED_SANDBOXES = {
    "/sandboxes": {"POST", "GET"},
    "/sandboxes/security/check": {"GET"},
    "/sandboxes/{sandbox_id}": {"GET", "DELETE"},
    "/sandboxes/{sandbox_id}/start": {"POST"},
    "/sandboxes/{sandbox_id}/stop": {"POST"},
    "/sandboxes/{sandbox_id}/execute": {"POST"},
    "/sandboxes/{sandbox_id}/executions": {"GET"},
    "/sandboxes/{sandbox_id}/executions/{execution_id}": {"GET"},
    "/sandboxes/{sandbox_id}/executions/{execution_id}/cancel": {"POST"},
    "/sandboxes/{sandbox_id}/events": {"GET"},
    "/sandboxes/{sandbox_id}/artifacts": {"GET"},
    "/sandboxes/{sandbox_id}/leases": {"POST"},
    "/sandboxes/{sandbox_id}/leases/{lease_id}/heartbeat": {"POST"},
    "/sandboxes/{sandbox_id}/leases/{lease_id}/release": {"POST"},
}

REQUIRED_PROFILES = {
    "/sandbox-profiles": {"POST", "GET"},
    "/sandbox-profiles/{name}": {"DELETE", "PATCH"},
}

REQUIRED_EXECUTIONS = {
    "/sandbox-executions/{execution_id}": {"GET"},
}


class TestSandboxApiContract:
    def test_sandbox_endpoints_registered(self):
        routes = _routes(sandboxes_router)
        for path, methods in REQUIRED_SANDBOXES.items():
            assert path in routes, f"missing sandbox route {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_profile_endpoints_registered(self):
        routes = _routes(sandbox_profiles_router)
        for path, methods in REQUIRED_PROFILES.items():
            assert path in routes, f"missing profile route {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_execution_lookup_registered(self):
        routes = _routes(sandbox_executions_router)
        for path, methods in REQUIRED_EXECUTIONS.items():
            assert path in routes, f"missing execution route {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_no_raw_secret_fields(self):
        """Request/response schemas must not accept raw secret values."""
        from openagent.api.v1.sandboxes import CreateSandboxRequest, ExecuteRequest
        create_fields = set(CreateSandboxRequest.model_fields)
        exec_fields = set(ExecuteRequest.model_fields)
        for forbidden in ("token", "secret", "password", "private_key", "api_key"):
            assert forbidden not in create_fields, forbidden
            assert forbidden not in exec_fields, forbidden
        assert "credential_refs" in exec_fields
