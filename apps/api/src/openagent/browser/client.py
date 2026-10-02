"""Policy-aware Python browser client (calls the canonical HTTP API).

The SDK never bypasses Tool Runtime, RBAC, or domain policy — it is a thin
typed wrapper over ``/api/v1/browser``.

Example:
    browser = BrowserClient(base_url="http://localhost:8000",
                            api_key="...", organization_id="...")
    session = browser.create_session(headless=True)
    page = browser.create_page(session["session_id"], url="https://example.com")
    task = browser.create_task(session["id"], objective="Summarize pricing")
    browser.act(task["id"], action_type="EXTRACT", page_id=page["id"],
                input_data={"selector": "body"})
"""

from __future__ import annotations

from typing import Any, Optional

import httpx


class BrowserClient:
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

    # -- sessions ------------------------------------------------------
    def create_session(self, headless: bool = True,
                       browser_profile_id: Optional[str] = None) -> dict[str, Any]:
        return self._req("POST", "/api/v1/browser/sessions",
                         {"headless": headless, "browser_profile_id": browser_profile_id})

    def list_sessions(self) -> list[dict[str, Any]]:
        return self._req("GET", "/api/v1/browser/sessions")

    def close_session(self, session_id: str) -> dict[str, Any]:
        return self._req("DELETE", f"/api/v1/browser/sessions/{session_id}")

    # -- pages ----------------------------------------------------------
    def create_page(self, session_id: str, url: Optional[str] = None) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/browser/sessions/{session_id}/pages",
                         {"url": url})

    # -- tasks -----------------------------------------------------------
    def create_task(self, session_id: str, objective: str,
                    max_steps: int = 100) -> dict[str, Any]:
        return self._req("POST", "/api/v1/browser/tasks",
                         {"browser_session_id": session_id, "objective": objective,
                          "max_steps": max_steps})

    def act(self, task_id: str, action_type: str, page_id: str,
            input_data: Optional[dict] = None, approved: bool = False) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/browser/tasks/{task_id}/actions",
                         {"action_type": action_type, "page_id": page_id,
                          "input": input_data or {}, "approved": approved})

    def observe(self, task_id: str, url: str, title: str = "", text: str = "",
                elements: Optional[list] = None, strategy: str = "standard") -> dict[str, Any]:
        return self._req("POST", f"/api/v1/browser/tasks/{task_id}/observations",
                         {"url": url, "title": title, "text": text,
                          "elements": elements or [], "strategy": strategy})

    def close(self) -> None:
        self._client.close()
