"""Browser API contract tests: route registration (no database required)."""

from openagent.api.v1.browser import router as browser_router


def _routes():
    out = {}
    for r in browser_router.routes:
        methods = tuple(sorted(getattr(r, "methods", set()) or set()))
        out.setdefault(getattr(r, "path", ""), set()).update(methods)
    return out


REQUIRED = {
    "/browser/sessions": {"POST", "GET"},
    "/browser/sessions/{session_id}": {"GET", "PATCH", "DELETE"},
    "/browser/sessions/{session_id}/pause": {"POST"},
    "/browser/sessions/{session_id}/resume": {"POST"},
    "/browser/sessions/{session_id}/heartbeat": {"POST"},
    "/browser/sessions/{session_id}/pages": {"POST", "GET"},
    "/browser/sessions/{session_id}/pages/{page_id}": {"DELETE"},
    "/browser/sessions/{session_id}/events": {"GET"},
    "/browser/tasks": {"POST", "GET"},
    "/browser/tasks/{task_id}": {"GET"},
    "/browser/tasks/{task_id}/actions": {"POST"},
    "/browser/tasks/{task_id}/observations": {"POST"},
    "/browser/tasks/{task_id}/cancel": {"POST"},
    "/browser/tasks/{task_id}/pause": {"POST"},
    "/browser/tasks/{task_id}/resume": {"POST"},
    "/browser/tasks/{task_id}/human": {"POST"},
    "/browser/profiles": {"POST", "GET"},
    "/browser/profiles/{profile_id}": {"GET", "PATCH", "DELETE"},
    "/browser/policies": {"POST", "GET", "PUT"},
    "/browser/health": {"GET"},
}


class TestBrowserApiContract:
    def test_all_spec_endpoints_registered(self):
        routes = _routes()
        for path, methods in REQUIRED.items():
            assert path in routes, f"missing browser route {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_health_is_public_get(self):
        routes = _routes()
        assert routes["/browser/health"] == {"GET"}
