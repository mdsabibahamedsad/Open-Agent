"""Policy-aware Python code client (calls the canonical HTTP API).

The SDK never bypasses Tool Runtime, RBAC, or policy — it is a thin typed
wrapper over ``/api/v1/repositories`` and ``/api/v1/code``.

Example:
    code = CodeClient(base_url="http://localhost:8000",
                      api_key="...", organization_id="...")
    repo = code.create_repository(provider="local", name="demo",
                                  full_name="demo", clone_url="/srv/git/demo.git")
    task = code.create_task(repository_id=repo["id"],
                            objective="Fix the failing authentication tests")
    print(code.task_diff(task["id"]))
"""

from __future__ import annotations

from typing import Any, Optional

import httpx


class CodeClient:
    def __init__(self, base_url: str, organization_id: str, api_key: Optional[str] = None,
                 timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.organization_id = organization_id
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
                "X-Organization-ID": organization_id,
            },
        )

    def _req(self, method: str, path: str, json: Any = None, params: Any = None) -> Any:
        r = self._client.request(method, path, json=json, params=params)
        r.raise_for_status()
        return r.json() if r.content else None

    # -- repositories --------------------------------------------------
    def create_repository(self, **kwargs: Any) -> dict[str, Any]:
        return self._req("POST", "/api/v1/repositories", kwargs)

    def list_repositories(self) -> list[dict[str, Any]]:
        return self._req("GET", "/api/v1/repositories")

    def connect_repository(self, repo_id: str) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/repositories/{repo_id}/connect")

    def sync_repository(self, repo_id: str) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/repositories/{repo_id}/sync")

    # -- workspaces ------------------------------------------------------
    def create_workspace(self, repository_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._req("POST", "/api/v1/code/workspaces",
                         {"repository_id": repository_id, **kwargs})

    def list_workspaces(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        params = {"status": status} if status else None
        return self._req("GET", "/api/v1/code/workspaces", params=params)

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return self._req("GET", f"/api/v1/code/workspaces/{workspace_id}")

    def delete_workspace(self, workspace_id: str, force: bool = False) -> Any:
        params = {"force": True} if force else None
        return self._req("DELETE", f"/api/v1/code/workspaces/{workspace_id}",
                         params=params)

    def create_branch(self, workspace_id: str, name: str) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/code/workspaces/{workspace_id}/branches",
                         {"name": name})

    def list_files(self, workspace_id: str, prefix: str = "") -> dict[str, Any]:
        params = {"prefix": prefix} if prefix else None
        return self._req("GET", f"/api/v1/code/workspaces/{workspace_id}/files",
                         params=params)

    def read_file(self, workspace_id: str, path: str,
                  start: Optional[int] = None,
                  end: Optional[int] = None) -> dict[str, Any]:
        params: dict[str, Any] = {"path": path}
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        return self._req("GET", f"/api/v1/code/workspaces/{workspace_id}/files/read",
                         params=params)

    def workspace_status(self, workspace_id: str) -> dict[str, Any]:
        return self._req("GET", f"/api/v1/code/workspaces/{workspace_id}/status")

    # -- tasks -------------------------------------------------------------
    def create_task(self, repository_id: str, objective: str,
                    **kwargs: Any) -> dict[str, Any]:
        """Create a coding task (workspace is provisioned server-side)."""
        return self._req("POST", "/api/v1/code/tasks",
                         {"repository_id": repository_id, "objective": objective,
                          **kwargs})

    def list_tasks(self, status: Optional[str] = None,
                   repository_id: Optional[str] = None) -> list[dict[str, Any]]:
        params = {k: v for k, v in
                  {"status": status, "repository_id": repository_id}.items()
                  if v is not None}
        return self._req("GET", "/api/v1/code/tasks", params=params or None)

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self._req("GET", f"/api/v1/code/tasks/{task_id}")

    def wait(self, task_id: str, timeout_s: float = 1800.0,
             interval_s: float = 5.0) -> dict[str, Any]:
        """Poll until the task reaches a terminal state or the timeout elapses."""
        import time
        terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT", "READY_FOR_PR"}
        deadline = time.monotonic() + timeout_s
        task = self.get_task(task_id)
        while task.get("status") not in terminal and time.monotonic() < deadline:
            time.sleep(interval_s)
            task = self.get_task(task_id)
        return task

    def result(self, task_id: str) -> dict[str, Any]:
        return {"task": self.get_task(task_id),
                "diff": self.task_diff(task_id),
                "events": self.task_events(task_id)}

    def cancel_task(self, task_id: str) -> Any:
        return self._req("POST", f"/api/v1/code/tasks/{task_id}/cancel", {})

    def pause_task(self, task_id: str) -> Any:
        return self._req("POST", f"/api/v1/code/tasks/{task_id}/pause", {})

    def resume_task(self, task_id: str) -> Any:
        return self._req("POST", f"/api/v1/code/tasks/{task_id}/resume", {})

    def task_plan(self, task_id: str) -> dict[str, Any]:
        return self._req("GET", f"/api/v1/code/tasks/{task_id}/plan")

    def task_artifacts(self, task_id: str) -> dict[str, Any]:
        return self._req("GET", f"/api/v1/code/tasks/{task_id}/artifacts")

    def apply_patch(self, task_id: str, diff: str,
                    approved: bool = False) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/code/tasks/{task_id}/patch",
                         {"diff": diff, "approved": approved})

    def commit(self, task_id: str, message: str) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/code/tasks/{task_id}/commit",
                         {"message": message})

    def push(self, task_id: str, approved: bool = False,
             force: bool = False) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/code/tasks/{task_id}/push",
                         {"approved": approved, "force": force})

    def plan_tests(self, task_id: str) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/code/tasks/{task_id}/tests/plan", {})

    def run_tests(self, command: str, task_id: Optional[str] = None,
                  workspace_id: Optional[str] = None) -> dict[str, Any]:
        return self._req("POST", "/api/v1/code/execute",
                         {"command": command, "profile": "TEST",
                          "task_id": task_id, "workspace_id": workspace_id})

    def task_diff(self, task_id: str) -> dict[str, Any]:
        return self._req("GET", f"/api/v1/code/tasks/{task_id}/diff")

    def task_events(self, task_id: str) -> list[dict[str, Any]]:
        return self._req("GET", f"/api/v1/code/tasks/{task_id}/events")

    # -- search / review / PR ----------------------------------------------
    def search(self, workspace_id: str, query: str,
               mode: str = "text", symbol: Optional[str] = None,
               regex: bool = False, top_k: int = 20) -> dict[str, Any]:
        body: dict[str, Any] = {"workspace_id": workspace_id, "query": query,
                                "mode": mode, "regex": regex, "top_k": top_k}
        if symbol is not None:
            body["symbol"] = symbol
        return self._req("POST", "/api/v1/code/search", body)

    def review_task(self, task_id: str) -> dict[str, Any]:
        return self._req("POST", "/api/v1/code/review", {"task_id": task_id})

    def review_text(self, filename: str, content: str) -> dict[str, Any]:
        return self._req("POST", "/api/v1/code/review",
                         {"filename": filename, "content": content})

    def prepare_pr(self, task_id: str, title: str, **kwargs: Any) -> dict[str, Any]:
        return self._req("POST", "/api/v1/code/pr",
                         {"task_id": task_id, "title": title, **kwargs})

    def close(self) -> None:
        self._client.close()
