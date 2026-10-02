"""GitLab official connector (MP21): issues and merge requests."""

from __future__ import annotations

from typing import Any

from openagent.connectors.errors import ProviderError, ProviderErrorKind
from openagent.connectors.providers._base import (
    base_url,
    bearer_headers,
    ok,
    schema,
    validate_input,
)

MANIFEST = {
    "id": "gitlab",
    "name": "GitLab",
    "version": "1.0.0",
    "category": "developer",
    "type": "OFFICIAL",
    "trust": "VERIFIED",
    "description": "GitLab projects, issues, and merge requests.",
    "publisher": "OpenAgent",
    "license": "Apache-2.0",
    "documentation_url": "https://docs.gitlab.com/ee/api/",
    "auth": {"type": "oauth2",
             "authorize_url": "https://gitlab.com/oauth/authorize",
             "token_url": "https://gitlab.com/oauth/token",
             "scopes": ["api"]},
    "capabilities": [
        {"id": "gitlab.issues.read", "description": "Read issues",
         "risk_level": "LOW"},
        {"id": "gitlab.issues.write", "description": "Create issues",
         "risk_level": "MEDIUM"},
        {"id": "gitlab.merge_requests.read", "description": "Read merge requests",
         "risk_level": "LOW"},
        {"id": "gitlab.merge_requests.write", "description": "Create merge requests",
         "risk_level": "MEDIUM"},
        {"id": "gitlab.merge_requests.merge", "description": "Merge merge requests",
         "risk_level": "HIGH"},
    ],
    "actions": [
        {"id": "gitlab.create_issue", "name": "Create issue",
         "description": "Create a project issue.",
         "input_schema": schema("object", {
             "project_id": {"type": "string"}, "title": {"type": "string"},
             "description": {"type": "string"},
             "labels": {"type": "string"}}, ["project_id", "title"]),
         "required_capabilities": ["gitlab.issues.write"],
         "risk_level": "MEDIUM", "timeout_seconds": 30,
         "rate_limit_per_minute": 30,
         "verification": {"kind": "side_effect"}},
        {"id": "gitlab.list_issues", "name": "List issues",
         "description": "List project issues.",
         "input_schema": schema("object", {
             "project_id": {"type": "string"}, "state": {"type": "string"}}),
         "required_capabilities": ["gitlab.issues.read"],
         "risk_level": "LOW", "mutation": False, "rate_limit_per_minute": 30},
        {"id": "gitlab.create_mr", "name": "Create merge request",
         "description": "Open a merge request.",
         "input_schema": schema("object", {
             "project_id": {"type": "string"}, "title": {"type": "string"},
             "source_branch": {"type": "string"},
             "target_branch": {"type": "string"},
             "description": {"type": "string"}},
             ["project_id", "title", "source_branch", "target_branch"]),
         "required_capabilities": ["gitlab.merge_requests.write"],
         "risk_level": "MEDIUM", "timeout_seconds": 30,
         "rate_limit_per_minute": 20,
         "verification": {"kind": "side_effect"}},
        {"id": "gitlab.merge_mr", "name": "Merge merge request",
         "description": "Merge a merge request (high-risk: requires approval).",
         "input_schema": schema("object", {
             "project_id": {"type": "string"},
             "mr_iid": {"type": "integer"},
             "squash": {"type": "boolean"}}, ["project_id", "mr_iid"]),
         "required_capabilities": ["gitlab.merge_requests.merge"],
         "risk_level": "HIGH", "timeout_seconds": 30,
         "rate_limit_per_minute": 20,
         "verification": {"kind": "side_effect"}},
    ],
    "triggers": [
        {"id": "gitlab.mr.opened", "name": "MR opened",
         "kind": "webhook", "event_types": ["merge_request.opened"]},
        {"id": "gitlab.issue.opened", "name": "Issue opened",
         "kind": "webhook", "event_types": ["issue.opened"]},
        {"id": "gitlab.push", "name": "Push", "kind": "webhook",
         "event_types": ["push"]},
    ],
    "resources": [
        {"kind": "issue", "provider_kind": "issue"},
        {"kind": "pull_request", "provider_kind": "merge_request"},
        {"kind": "user", "provider_kind": "user"},
    ],
    "scopes": ["api"],
    "rate_limits": {"per_minute": 30},
}

_DEFAULT_BASE = "https://gitlab.com/api/v4"


def _project(value: str) -> str:
    from urllib.parse import quote
    text = str(value or "")
    if not text or len(text) > 256 or ".." in text:
        raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                            "Invalid project id/path")
    return quote(text, safe="")


async def execute(action_id: str, params: dict[str, Any],
                  auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    http = ctx["http"]
    base = base_url(auth, _DEFAULT_BASE)
    headers = bearer_headers(auth)
    short = action_id.split(".", 1)[1] if "." in action_id else action_id
    if short == "create_issue":
        params = validate_input(_schema_of(action_id), params, action_id)
        project = _project(params["project_id"])
        resp = await http.request(
            "POST", f"{base}/projects/{project}/issues", headers=headers,
            json_body={"title": params["title"],
                       "description": params.get("description", ""),
                       "labels": params.get("labels", "")},
            timeout_seconds=30, max_attempts=2, idempotent=True)
        body = resp.body if isinstance(resp.body, dict) else {}
        return ok(action_id, {"id": body.get("id"), "iid": body.get("iid"),
                              "web_url": body.get("web_url", "")},
                  provider_request_id=resp.provider_request_id, verified=True)
    if short == "list_issues":
        params = validate_input(_schema_of(action_id), params, action_id)
        project = _project(params.get("project_id", ""))
        query: dict[str, Any] = {"per_page": 20}
        if params.get("state"):
            query["state"] = params["state"]
        resp = await http.request(
            "GET", f"{base}/projects/{project}/issues", headers=headers,
            params=query, timeout_seconds=30, max_attempts=3, idempotent=True)
        items = resp.body if isinstance(resp.body, list) else []
        return ok(action_id, {"issues": [
            {"id": i.get("id"), "iid": i.get("iid"), "title": i.get("title"),
             "state": i.get("state")} for i in items if isinstance(i, dict)]},
            provider_request_id=resp.provider_request_id, verified=True)
    if short == "create_mr":
        params = validate_input(_schema_of(action_id), params, action_id)
        project = _project(params["project_id"])
        for ref in (params["source_branch"], params["target_branch"]):
            if not ref or ".." in ref or ref.startswith(("-", ".")):
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    "Invalid branch")
        resp = await http.request(
            "POST", f"{base}/projects/{project}/merge_requests",
            headers=headers,
            json_body={"title": params["title"],
                       "source_branch": params["source_branch"],
                       "target_branch": params["target_branch"],
                       "description": params.get("description", "")},
            timeout_seconds=30, max_attempts=2, idempotent=True)
        body = resp.body if isinstance(resp.body, dict) else {}
        return ok(action_id, {"id": body.get("id"), "iid": body.get("iid"),
                              "web_url": body.get("web_url", "")},
                  provider_request_id=resp.provider_request_id, verified=True)
    if short == "merge_mr":
        params = validate_input(_schema_of(action_id), params, action_id)
        project = _project(params["project_id"])
        resp = await http.request(
            "PUT",
            f"{base}/projects/{project}/merge_requests/{int(params['mr_iid'])}/merge",
            headers=headers,
            json_body={"squash": bool(params.get("squash", False))},
            timeout_seconds=30, max_attempts=1, idempotent=False)
        body = resp.body if isinstance(resp.body, dict) else {}
        return ok(action_id, {"state": body.get("state", ""),
                              "sha": body.get("sha", "")},
                  provider_request_id=resp.provider_request_id, verified=True)
    raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                        f"Unknown action '{action_id}'")


async def test(auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    http = ctx["http"]
    base = base_url(auth, _DEFAULT_BASE)
    headers = bearer_headers(auth)
    resp = await http.request("GET", f"{base}/user", headers=headers,
                              timeout_seconds=15, max_attempts=2, idempotent=True)
    body = resp.body if isinstance(resp.body, dict) else {}
    return {"provider": "gitlab", "username": body.get("username", "")}


def normalize_event(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload.get("object_kind", ""))
    attrs = payload.get("object_attributes", {}) if isinstance(payload, dict) else {}
    mapping = {("merge_request", "open"): "merge_request.opened",
               ("issue", "open"): "issue.opened",
               ("push", ""): "push"}
    return {"event_type": mapping.get((kind, attrs.get("action", "")), kind or event),
            "resource_id": str(attrs.get("id", "")),
            "attributes": {}}


def _schema_of(action_id: str) -> dict[str, Any]:
    for action in MANIFEST["actions"]:
        if action["id"] == action_id:
            return action["input_schema"]
    return {"type": "object"}
