"""Code API contract tests: route registration (no database required)."""

from openagent.api.v1.code import router as code_router
from openagent.api.v1.repositories import router as repos_router


def _routes(router):
    out = {}
    for r in router.routes:
        methods = tuple(sorted(getattr(r, "methods", set()) or set()))
        out.setdefault(getattr(r, "path", ""), set()).update(methods)
    return out


REQUIRED_REPOS = {
    "/repositories": {"POST", "GET"},
    "/repositories/{repo_id}": {"GET", "DELETE"},
    "/repositories/{repo_id}/connect": {"POST"},
    "/repositories/{repo_id}/sync": {"POST"},
    "/repositories/remote/list": {"POST"},
}

REQUIRED_CODE = {
    "/code/workspaces": {"POST", "GET"},
    "/code/workspaces/{ws_id}": {"GET", "DELETE"},
    "/code/workspaces/{ws_id}/status": {"GET"},
    "/code/workspaces/{ws_id}/branches": {"POST"},
    "/code/workspaces/{ws_id}/files": {"GET"},
    "/code/workspaces/{ws_id}/files/read": {"GET"},
    "/code/tasks": {"POST", "GET"},
    "/code/tasks/{task_id}": {"GET"},
    "/code/tasks/{task_id}/cancel": {"POST"},
    "/code/tasks/{task_id}/pause": {"POST"},
    "/code/tasks/{task_id}/resume": {"POST"},
    "/code/tasks/{task_id}/diff": {"GET"},
    "/code/tasks/{task_id}/events": {"GET"},
    "/code/tasks/{task_id}/artifacts": {"GET"},
    "/code/tasks/{task_id}/patch": {"POST"},
    "/code/tasks/{task_id}/commit": {"POST"},
    "/code/tasks/{task_id}/push": {"POST"},
    "/code/tasks/{task_id}/plan": {"GET"},
    "/code/tasks/{task_id}/tests/plan": {"POST"},
    "/code/search": {"POST"},
    "/code/review": {"POST"},
    "/code/execute": {"POST"},
    "/code/pr": {"POST"},
    "/code/health": {"GET"},
}


class TestCodeApiContract:
    def test_repository_endpoints_registered(self):
        routes = _routes(repos_router)
        for path, methods in REQUIRED_REPOS.items():
            assert path in routes, f"missing repository route {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_code_endpoints_registered(self):
        routes = _routes(code_router)
        for path, methods in REQUIRED_CODE.items():
            assert path in routes, f"missing code route {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_no_filesystem_paths_in_schemas(self):
        # Workspace responses must never expose host paths: assert by schema.
        from openagent.api.v1.code import WorkspaceResponse
        assert "filesystem_root" not in WorkspaceResponse.model_fields
