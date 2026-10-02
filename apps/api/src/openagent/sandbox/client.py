"""Policy-aware Python sandbox client (calls the canonical HTTP API).

The SDK never bypasses Tool Runtime, RBAC, or policy — it is a thin typed
wrapper over ``/api/v1/sandboxes`` and ``/api/v1/sandbox-profiles``.

Example:
    sbx = SandboxClient(base_url="http://localhost:8000",
                        api_key="...", organization_id="...")
    sb = sbx.create(profile="TEST")
    sbx.start(sb["id"])
    result = sbx.execute(sb["id"], ["pytest", "tests/"])
    print(result["status"], result["exit_code"])
"""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx


class SandboxClient:
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

    # -- sandboxes -------------------------------------------------------
    def create(self, profile: str = "TEST", **kwargs: Any) -> dict[str, Any]:
        return self._req("POST", "/api/v1/sandboxes", {"profile": profile, **kwargs})

    def list(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        return self._req("GET", "/api/v1/sandboxes",
                         params={"status": status} if status else None)

    def get(self, sandbox_id: str) -> dict[str, Any]:
        return self._req("GET", f"/api/v1/sandboxes/{sandbox_id}")

    def start(self, sandbox_id: str) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/sandboxes/{sandbox_id}/start", {})

    def stop(self, sandbox_id: str) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/sandboxes/{sandbox_id}/stop", {})

    def destroy(self, sandbox_id: str) -> Any:
        return self._req("DELETE", f"/api/v1/sandboxes/{sandbox_id}")

    # -- execution ---------------------------------------------------------
    def execute(self, sandbox_id: str, command: Any,
                workdir: str = "/workspace", **kwargs: Any) -> dict[str, Any]:
        """Execute a command (argv list preferred: ["pytest", "tests/"])."""
        return self._req("POST", f"/api/v1/sandboxes/{sandbox_id}/execute",
                         {"command": command, "workdir": workdir, **kwargs})

    def wait(self, execution_id: str, sandbox_id: Optional[str] = None,
             timeout_s: float = 1800.0, interval_s: float = 5.0) -> dict[str, Any]:
        """Poll an execution until terminal state or timeout."""
        terminal = {"SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED", "KILLED",
                    "RESOURCE_LIMIT", "POLICY_DENIED", "SANDBOX_ERROR",
                    "WAITING_FOR_APPROVAL"}
        deadline = time.monotonic() + timeout_s
        ex = self.get_execution(execution_id, sandbox_id)
        while ex.get("status") not in terminal and time.monotonic() < deadline:
            time.sleep(interval_s)
            ex = self.get_execution(execution_id, sandbox_id)
        return ex

    def get_execution(self, execution_id: str,
                      sandbox_id: Optional[str] = None) -> dict[str, Any]:
        if sandbox_id:
            return self._req(
                "GET", f"/api/v1/sandboxes/{sandbox_id}/executions/{execution_id}")
        return self._req("GET", f"/api/v1/sandbox-executions/{execution_id}")

    def cancel(self, sandbox_id: str, execution_id: str) -> Any:
        return self._req(
            "POST",
            f"/api/v1/sandboxes/{sandbox_id}/executions/{execution_id}/cancel", {})

    def list_executions(self, sandbox_id: str) -> list[dict[str, Any]]:
        return self._req("GET", f"/api/v1/sandboxes/{sandbox_id}/executions")

    def events(self, sandbox_id: str) -> list[dict[str, Any]]:
        return self._req("GET", f"/api/v1/sandboxes/{sandbox_id}/events")

    def artifacts(self, sandbox_id: str) -> list[dict[str, Any]]:
        return self._req("GET", f"/api/v1/sandboxes/{sandbox_id}/artifacts")

    # -- leases / profiles ---------------------------------------------------
    def acquire_lease(self, sandbox_id: str, owner: str,
                      ttl_seconds: int = 600) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/sandboxes/{sandbox_id}/leases",
                         {"owner": owner, "ttl_seconds": ttl_seconds})

    def list_profiles(self) -> list[dict[str, Any]]:
        return self._req("GET", "/api/v1/sandbox-profiles")

    def security_check(self) -> dict[str, Any]:
        return self._req("GET", "/api/v1/sandboxes/security/check")

    def close(self) -> None:
        self._client.close()
