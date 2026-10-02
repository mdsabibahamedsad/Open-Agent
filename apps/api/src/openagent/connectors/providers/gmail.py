"""Gmail official connector (MP21): read + send via Gmail API."""

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
    "id": "gmail",
    "name": "Gmail",
    "version": "1.0.0",
    "category": "communication",
    "type": "OFFICIAL",
    "trust": "VERIFIED",
    "description": "Gmail messages: list, read, and send.",
    "publisher": "OpenAgent",
    "license": "Apache-2.0",
    "documentation_url": "https://developers.google.com/gmail/api",
    "auth": {"type": "oauth2",
             "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
             "token_url": "https://oauth2.googleapis.com/token",
             "scopes": ["https://www.googleapis.com/auth/gmail.readonly",
                        "https://www.googleapis.com/auth/gmail.send"]},
    "capabilities": [
        {"id": "gmail.messages.read", "description": "Read messages",
         "risk_level": "LOW"},
        {"id": "gmail.messages.write", "description": "Send messages",
         "risk_level": "HIGH"},
    ],
    "actions": [
        {"id": "gmail.list_messages", "name": "List messages",
         "description": "List message IDs matching a query.",
         "input_schema": schema("object", {
             "q": {"type": "string"}, "max_results": {"type": "integer"}}),
         "required_capabilities": ["gmail.messages.read"],
         "risk_level": "LOW", "mutation": False, "rate_limit_per_minute": 30},
        {"id": "gmail.get_message", "name": "Get message",
         "description": "Fetch one message (metadata + snippet).",
         "input_schema": schema("object", {"id": {"type": "string"}}, ["id"]),
         "required_capabilities": ["gmail.messages.read"],
         "risk_level": "LOW", "mutation": False, "rate_limit_per_minute": 30},
        {"id": "gmail.send_message", "name": "Send message",
         "description": "Send an email (external side effect, high risk).",
         "input_schema": schema("object", {
             "to": {"type": "string"}, "subject": {"type": "string"},
             "body": {"type": "string"}}, ["to", "subject", "body"]),
         "required_capabilities": ["gmail.messages.write"],
         "risk_level": "HIGH", "timeout_seconds": 30,
         "rate_limit_per_minute": 20,
         "verification": {"kind": "side_effect"}},
    ],
    "triggers": [
        {"id": "gmail.message.received", "name": "Message received",
         "kind": "polling",
         "poll_config": {"interval_seconds": 300, "cursor": "historyId"},
         "description": "Poll for new messages (Gmail push needs GCP Pub/Sub)."},
    ],
    "resources": [{"kind": "message", "provider_kind": "gmail_message"}],
    "scopes": ["https://www.googleapis.com/auth/gmail.readonly",
               "https://www.googleapis.com/auth/gmail.send"],
    "rate_limits": {"per_minute": 30},
}

_DEFAULT_BASE = "https://gmail.googleapis.com/gmail/v1"


async def execute(action_id: str, params: dict[str, Any],
                  auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    http = ctx["http"]
    base = base_url(auth, _DEFAULT_BASE)
    headers = bearer_headers(auth)
    short = action_id.split(".", 1)[1] if "." in action_id else action_id
    if short == "list_messages":
        params = validate_input(_schema_of(action_id), params, action_id)
        resp = await http.request(
            "GET", f"{base}/users/me/messages", headers=headers,
            params={"q": params.get("q", ""),
                    "maxResults": min(int(params.get("max_results", 20) or 20), 100)},
            timeout_seconds=30, max_attempts=3, idempotent=True)
        body = resp.body if isinstance(resp.body, dict) else {}
        messages = body.get("messages", []) or []
        return ok(action_id, {"messages": [
            {"id": m.get("id"), "threadId": m.get("threadId")} for m in messages
            if isinstance(m, dict)]},
            provider_request_id=resp.provider_request_id, verified=True)
    if short == "get_message":
        params = validate_input(_schema_of(action_id), params, action_id)
        message_id = "".join(c for c in params["id"] if c.isalnum())
        if not message_id:
            raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                "Invalid message id")
        resp = await http.request(
            "GET", f"{base}/users/me/messages/{message_id}", headers=headers,
            params={"format": "metadata",
                    "metadataHeaders": ["From", "To", "Subject", "Date"]},
            timeout_seconds=30, max_attempts=3, idempotent=True)
        body = resp.body if isinstance(resp.body, dict) else {}
        headers_out = {h.get("name"): h.get("value")
                       for h in (body.get("payload") or {}).get("headers", [])
                       if isinstance(h, dict)}
        return ok(action_id, {"id": body.get("id", ""),
                              "snippet": (body.get("snippet", "") or "")[:2000],
                              "headers": headers_out},
                  provider_request_id=resp.provider_request_id, verified=True)
    if short == "send_message":
        params = validate_input(_schema_of(action_id), params, action_id)
        to = str(params["to"])
        if "@" not in to or len(to) > 320:
            raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                "Invalid recipient")
        import base64
        from email.message import EmailMessage
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = str(params["subject"])[:500]
        message.set_content(str(params["body"])[:20000])
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        resp = await http.request(
            "POST", f"{base}/users/me/messages/send", headers=headers,
            json_body={"raw": raw}, timeout_seconds=30, max_attempts=2,
            idempotent=False)
        body = resp.body if isinstance(resp.body, dict) else {}
        return ok(action_id, {"id": body.get("id", ""),
                              "threadId": body.get("threadId", "")},
                  provider_request_id=resp.provider_request_id, verified=True)
    raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                        f"Unknown action '{action_id}'")


async def test(auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    http = ctx["http"]
    base = base_url(auth, _DEFAULT_BASE)
    headers = bearer_headers(auth)
    resp = await http.request("GET", f"{base}/users/me/profile",
                              headers=headers, timeout_seconds=15,
                              max_attempts=2, idempotent=True)
    body = resp.body if isinstance(resp.body, dict) else {}
    return {"provider": "gmail", "email": body.get("emailAddress", "")}


def normalize_event(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"event_type": "message.received",
            "resource_id": str(payload.get("id", "")),
            "attributes": {}}


def _schema_of(action_id: str) -> dict[str, Any]:
    for action in MANIFEST["actions"]:
        if action["id"] == action_id:
            return action["input_schema"]
    return {"type": "object"}
