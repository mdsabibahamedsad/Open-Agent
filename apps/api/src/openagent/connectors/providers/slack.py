"""Slack official connector (MP21): channels, messages, history."""

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
    "id": "slack",
    "name": "Slack",
    "version": "1.0.0",
    "category": "communication",
    "type": "OFFICIAL",
    "trust": "VERIFIED",
    "description": "Slack channels and messaging.",
    "publisher": "OpenAgent",
    "license": "Apache-2.0",
    "documentation_url": "https://api.slack.com/",
    "auth": {"type": "oauth2",
             "authorize_url": "https://slack.com/oauth/v2/authorize",
             "token_url": "https://slack.com/api/oauth.v2.access",
             "scopes": ["channels:read", "chat:write", "channels:history"]},
    "capabilities": [
        {"id": "slack.channels.read", "description": "List channels",
         "risk_level": "LOW"},
        {"id": "slack.messages.read", "description": "Read channel history",
         "risk_level": "LOW"},
        {"id": "slack.messages.write", "description": "Send messages",
         "risk_level": "MEDIUM"},
    ],
    "actions": [
        {"id": "slack.list_channels", "name": "List channels",
         "description": "List public channels in the workspace.",
         "input_schema": schema("object", {"limit": {"type": "integer"}}),
         "required_capabilities": ["slack.channels.read"],
         "risk_level": "LOW", "mutation": False, "rate_limit_per_minute": 30},
        {"id": "slack.send_message", "name": "Send message",
         "description": "Post a message to a channel (external side effect).",
         "input_schema": schema("object", {
             "channel": {"type": "string"}, "text": {"type": "string"}},
             ["channel", "text"]),
         "required_capabilities": ["slack.messages.write"],
         "risk_level": "MEDIUM", "supports_idempotency": False,
         "timeout_seconds": 30, "rate_limit_per_minute": 30,
         "verification": {"kind": "side_effect"}},
        {"id": "slack.get_history", "name": "Channel history",
         "description": "Read recent messages from a channel.",
         "input_schema": schema("object", {
             "channel": {"type": "string"}, "limit": {"type": "integer"}},
             ["channel"]),
         "required_capabilities": ["slack.messages.read"],
         "risk_level": "LOW", "mutation": False, "rate_limit_per_minute": 30},
    ],
    "triggers": [
        {"id": "slack.message.created", "name": "Message posted",
         "kind": "webhook", "event_types": ["message.created"]},
    ],
    "resources": [
        {"kind": "message", "provider_kind": "message"},
        {"kind": "user", "provider_kind": "user"},
    ],
    "scopes": ["channels:read", "chat:write", "channels:history"],
    "rate_limits": {"per_minute": 30},
}

_DEFAULT_BASE = "https://slack.com/api"


def _check(resp_body: Any, action_id: str) -> dict[str, Any]:
    if not isinstance(resp_body, dict) or not resp_body.get("ok"):
        error = resp_body.get("error", "unknown") if isinstance(resp_body, dict) else "unknown"
        if error in ("invalid_auth", "token_revoked", "account_inactive"):
            raise ProviderError(ProviderErrorKind.AUTHENTICATION_ERROR,
                                f"Slack auth failed: {error}")
        if error == "ratelimited":
            raise ProviderError(ProviderErrorKind.RATE_LIMITED,
                                "Slack rate limited")
        if error in ("channel_not_found", "user_not_found"):
            raise ProviderError(ProviderErrorKind.NOT_FOUND, f"Slack: {error}")
        raise ProviderError(ProviderErrorKind.PROVIDER_UNAVAILABLE,
                            f"Slack error: {error}")
    return resp_body


async def execute(action_id: str, params: dict[str, Any],
                  auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    http = ctx["http"]
    base = base_url(auth, _DEFAULT_BASE)
    headers = bearer_headers(auth)
    short = action_id.split(".", 1)[1] if "." in action_id else action_id
    if short == "list_channels":
        params = validate_input(_schema_of(action_id), params, action_id)
        limit = min(int(params.get("limit", 50) or 50), 200)
        resp = await http.request(
            "GET", f"{base}/conversations.list", headers=headers,
            params={"limit": limit, "exclude_archived": "true"},
            timeout_seconds=30, max_attempts=3, idempotent=True)
        body = _check(resp.body, action_id)
        channels = body.get("channels", []) or []
        return ok(action_id, {"channels": [
            {"id": c.get("id"), "name": c.get("name")} for c in channels
            if isinstance(c, dict)]},
            provider_request_id=resp.provider_request_id, verified=True)
    if short == "send_message":
        params = validate_input(_schema_of(action_id), params, action_id)
        text = str(params.get("text", ""))
        if not text.strip() or len(text) > 8000:
            raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                "Message text must be 1..8000 chars")
        resp = await http.request(
            "POST", f"{base}/chat.postMessage", headers=headers,
            json_body={"channel": params["channel"], "text": text},
            timeout_seconds=30, max_attempts=2, idempotent=False)
        body = _check(resp.body, action_id)
        return ok(action_id, {"ts": body.get("ts", ""),
                              "channel": body.get("channel", "")},
                  provider_request_id=resp.provider_request_id, verified=True)
    if short == "get_history":
        params = validate_input(_schema_of(action_id), params, action_id)
        limit = min(int(params.get("limit", 20) or 20), 100)
        resp = await http.request(
            "GET", f"{base}/conversations.history", headers=headers,
            params={"channel": params["channel"], "limit": limit},
            timeout_seconds=30, max_attempts=3, idempotent=True)
        body = _check(resp.body, action_id)
        messages = body.get("messages", []) or []
        return ok(action_id, {"messages": [
            {"ts": m.get("ts"), "user": m.get("user"),
             "text": (m.get("text", "") or "")[:2000]} for m in messages
            if isinstance(m, dict)]},
            provider_request_id=resp.provider_request_id, verified=True)
    raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                        f"Unknown action '{action_id}'")


async def test(auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    http = ctx["http"]
    base = base_url(auth, _DEFAULT_BASE)
    headers = bearer_headers(auth)
    resp = await http.request("GET", f"{base}/auth.test", headers=headers,
                              timeout_seconds=15, max_attempts=2, idempotent=True)
    body = _check(resp.body, "slack.test")
    return {"provider": "slack", "team": body.get("team", ""),
            "user": body.get("user", "")}


def normalize_event(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    inner = payload.get("event", {}) if isinstance(payload, dict) else {}
    return {"event_type": "message.created",
            "resource_id": str(inner.get("ts") or payload.get("event_id", "")),
            "attributes": {"channel": inner.get("channel", ""),
                           "user": inner.get("user", "")}}


def _schema_of(action_id: str) -> dict[str, Any]:
    for action in MANIFEST["actions"]:
        if action["id"] == action_id:
            return action["input_schema"]
    return {"type": "object"}
