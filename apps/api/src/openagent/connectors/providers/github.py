"""GitHub official connector (MP21): issues, PRs, repositories."""

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
    "id": "github",
    "name": "GitHub",
    "version": "1.0.0",
    "category": "developer",
    "type": "OFFICIAL",
    "trust": "VERIFIED",
    "description": "GitHub repositories, issues, and pull requests.",
    "publisher": "OpenAgent",
    "license": "Apache-2.0",
    "documentation_url": "https://docs.github.com/en/rest",
    "auth": {"type": "oauth2",
             "authorize_url": "https://github.com/login/oauth/authorize",
             "token_url": "https://github.com/login/oauth/access_token",
             "scopes": ["repo", "read:org"]},
    "capabilities": [
        {"id": "github.repositories.read", "description": "Read repositories",
         "risk_level": "LOW"},
        {"id": "github.issues.read", "description": "Read issues",
         "risk_level": "LOW"},
        {"id": "github.issues.write", "description": "Create/update issues",
         "risk_level": "MEDIUM"},
        {"id": "github.pull_requests.read", "description": "Read pull requests",
         "risk_level": "LOW"},
        {"id": "github.pull_requests.write", "description": "Create pull requests",
         "risk_level": "MEDIUM"},
        {"id": "github.pull_requests.merge", "description": "Merge pull requests",
         "risk_level": "HIGH"},
    ],
    "actions": [
        {"id": "github.list_repos", "name": "List repositories",
         "description": "List repositories for the authenticated user.",
         "input_schema": schema("object", {"per_page": {"type": "integer"},
                                           "visibility": {"type": "string"}}),
         "required_capabilities": ["github.repositories.read"],
         "risk_level": "LOW", "mutation": False, "timeout_seconds": 30,
         "rate_limit_per_minute": 30},
        {"id": "github.create_issue", "name": "Create issue",
         "description": "Create an issue in a repository.",
         "input_schema": schema("object", {
             "owner": {"type": "string"}, "repo": {"type": "string"},
             "title": {"type": "string"}, "body": {"type": "string"},
             "labels": {"type": "array"}}, ["owner", "repo", "title"]),
         "required_capabilities": ["github.issues.write"],
         "risk_level": "MEDIUM", "supports_idempotency": True,
         "idempotency_strategy": "dedupe-by-title", "timeout_seconds": 30,
         "rate_limit_per_minute": 30,
         "verification": {"kind": "side_effect"}},
        {"id": "github.get_issue", "name": "Get issue",
         "description": "Fetch a single issue.",
         "input_schema": schema("object", {
             "owner": {"type": "string"}, "repo": {"type": "string"},
             "number": {"type": "integer"}}, ["owner", "repo", "number"]),
         "required_capabilities": ["github.issues.read"],
         "risk_level": "LOW", "mutation": False},
        {"id": "github.create_pr", "name": "Create pull request",
         "description": "Open a pull request.",
         "input_schema": schema("object", {
             "owner": {"type": "string"}, "repo": {"type": "string"},
             "title": {"type": "string"}, "head": {"type": "string"},
             "base": {"type": "string"}, "body": {"type": "string"}},
             ["owner", "repo", "title", "head", "base"]),
         "required_capabilities": ["github.pull_requests.write"],
         "risk_level": "MEDIUM", "timeout_seconds": 30,
         "rate_limit_per_minute": 20,
         "verification": {"kind": "side_effect"}},
        {"id": "github.merge_pr", "name": "Merge pull request",
         "description": "Merge a pull request (high-risk: requires approval).",
         "input_schema": schema("object", {
             "owner": {"type": "string"}, "repo": {"type": "string"},
             "number": {"type": "integer"},
             "merge_method": {"type": "string", "enum": ["merge", "squash", "rebase"]}},
             ["owner", "repo", "number"]),
         "required_capabilities": ["github.pull_requests.merge"],
         "risk_level": "HIGH", "timeout_seconds": 30,
         "rate_limit_per_minute": 20,
         "verification": {"kind": "side_effect"}},
    ],
    "triggers": [
        {"id": "github.pull_request.opened", "name": "PR opened",
         "kind": "webhook", "event_types": ["pull_request.opened"],
         "description": "Fires when a pull request is opened."},
        {"id": "github.issue.opened", "name": "Issue opened",
         "kind": "webhook", "event_types": ["issues.opened"]},
        {"id": "github.push", "name": "Push", "kind": "webhook",
         "event_types": ["push"]},
    ],
    "resources": [
        {"kind": "repository", "provider_kind": "repository"},
        {"kind": "issue", "provider_kind": "issue"},
        {"kind": "pull_request", "provider_kind": "pull_request"},
        {"kind": "user", "provider_kind": "user"},
    ],
    "scopes": ["repo", "read:org"],
    "rate_limits": {"per_minute": 30, "per_hour": 1000},
}

_DEFAULT_BASE = "https://api.github.com"


async def execute(action_id: str, params: dict[str, Any],
                  auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    http = ctx["http"]
    base = base_url(auth, _DEFAULT_BASE)
    headers = bearer_headers(auth, extra={"Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28"})
    short = action_id.split(".", 1)[1] if "." in action_id else action_id
    if short == "list_repos":
        params = validate_input(_schema_of("github.list_repos"), params, action_id)
        resp = await http.request(
            "GET", f"{base}/user/repos", headers=headers,
            params={"per_page": params.get("per_page", 30),
                    "visibility": params.get("visibility", "all")},
            timeout_seconds=30, max_attempts=3, idempotent=True)
        repos = resp.body if isinstance(resp.body, list) else []
        return ok(action_id, {"repositories": [
            {"id": r.get("id"), "full_name": r.get("full_name"),
             "html_url": r.get("html_url"),
             "default_branch": r.get("default_branch")} for r in repos
            if isinstance(r, dict)]},
            provider_request_id=resp.provider_request_id, verified=True)
    if short == "create_issue":
        params = validate_input(_schema_of("github.create_issue"), params, action_id)
        owner, repo = params["owner"], params["repo"]
        _assert_repo_path(owner, repo)
        resp = await http.request(
            "POST", f"{base}/repos/{owner}/{repo}/issues", headers=headers,
            json_body={"title": params["title"], "body": params.get("body", ""),
                       "labels": params.get("labels", [])},
            timeout_seconds=30, max_attempts=2, idempotent=True)
        issue = resp.body if isinstance(resp.body, dict) else {}
        return ok(action_id, {"id": issue.get("id"), "number": issue.get("number"),
                              "html_url": issue.get("html_url")},
                  provider_request_id=resp.provider_request_id, verified=True)
    if short == "get_issue":
        params = validate_input(_schema_of("github.get_issue"), params, action_id)
        owner, repo, number = params["owner"], params["repo"], int(params["number"])
        _assert_repo_path(owner, repo)
        resp = await http.request(
            "GET", f"{base}/repos/{owner}/{repo}/issues/{number}",
            headers=headers, timeout_seconds=30, max_attempts=3, idempotent=True)
        issue = resp.body if isinstance(resp.body, dict) else {}
        return ok(action_id, {"number": issue.get("number"),
                              "title": issue.get("title"),
                              "state": issue.get("state"),
                              "html_url": issue.get("html_url")},
                  provider_request_id=resp.provider_request_id, verified=True)
    if short == "create_pr":
        params = validate_input(_schema_of("github.create_pr"), params, action_id)
        owner, repo = params["owner"], params["repo"]
        _assert_repo_path(owner, repo)
        for ref in (params["head"], params["base"]):
            if not ref or ".." in ref or ref.startswith(("-", ".")):
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    "Invalid git ref")
        resp = await http.request(
            "POST", f"{base}/repos/{owner}/{repo}/pulls", headers=headers,
            json_body={"title": params["title"], "head": params["head"],
                       "base": params["base"], "body": params.get("body", "")},
            timeout_seconds=30, max_attempts=2, idempotent=True)
        pr = resp.body if isinstance(resp.body, dict) else {}
        return ok(action_id, {"number": pr.get("number"),
                              "html_url": pr.get("html_url")},
                  provider_request_id=resp.provider_request_id, verified=True)
    if short == "merge_pr":
        params = validate_input(_schema_of("github.merge_pr"), params, action_id)
        owner, repo, number = params["owner"], params["repo"], int(params["number"])
        _assert_repo_path(owner, repo)
        method = params.get("merge_method", "merge")
        if method not in ("merge", "squash", "rebase"):
            raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                "Invalid merge method")
        resp = await http.request(
            "PUT", f"{base}/repos/{owner}/{repo}/pulls/{number}/merge",
            headers=headers, json_body={"merge_method": method},
            timeout_seconds=30, max_attempts=1, idempotent=False)
        merged = resp.body if isinstance(resp.body, dict) else {}
        return ok(action_id, {"merged": bool(merged.get("merged")),
                              "sha": merged.get("sha", "")},
                  provider_request_id=resp.provider_request_id, verified=True)
    raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                        f"Unknown action '{action_id}'")


async def test(auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    http = ctx["http"]
    base = base_url(auth, _DEFAULT_BASE)
    headers = bearer_headers(auth)
    resp = await http.request("GET", f"{base}/user", headers=headers,
                              timeout_seconds=15, max_attempts=2, idempotent=True)
    user = resp.body if isinstance(resp.body, dict) else {}
    return {"provider": "github", "login": user.get("login", ""),
            "id": user.get("id", "")}


def normalize_event(event: str, payload: dict[str, Any],
                    headers: dict[str, Any] | None = None) -> dict[str, Any]:
    lowered = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    name, _, action = (event or lowered.get("x-github-event", "unknown")).partition(".")
    if not action:
        action = str(payload.get("action", ""))
    resource_id = ""
    if name == "pull_request":
        resource_id = str((payload.get("pull_request") or {}).get("id", ""))
    elif name == "issues":
        resource_id = str((payload.get("issue") or {}).get("id", ""))
    elif name == "push":
        resource_id = str(payload.get("after", ""))
    return {"event_type": f"{name}.{action}" if action else name,
            "resource_id": resource_id,
            "attributes": {"repository": ((payload.get("repository") or {})
                                          .get("full_name", ""))}}


def _schema_of(action_id: str) -> dict[str, Any]:
    for action in MANIFEST["actions"]:
        if action["id"] == action_id:
            return action["input_schema"]
    return {"type": "object"}


def _assert_repo_path(owner: str, repo: str) -> None:
    import re
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", owner or "") or \
            not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", repo or ""):
        raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                            "Invalid owner/repo path")
