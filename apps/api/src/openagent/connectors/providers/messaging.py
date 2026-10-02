"""Discord + Telegram official connectors (MP21): messaging via bot APIs."""

from __future__ import annotations

from typing import Any

from openagent.connectors.errors import ProviderError, ProviderErrorKind
from openagent.connectors.providers._base import (
    base_url,
    bearer_headers,
    ok,
    schema,
    secrets_of,
    validate_input,
)

DISCORD_MANIFEST = {
    "id": "discord",
    "name": "Discord",
    "version": "1.0.0",
    "category": "communication",
    "type": "OFFICIAL",
    "trust": "VERIFIED",
    "description": "Discord channels and messaging.",
    "publisher": "OpenAgent",
    "license": "Apache-2.0",
    "documentation_url": "https://discord.com/developers/docs/intro",
    "auth": {"type": "oauth2",
             "authorize_url": "https://discord.com/oauth2/authorize",
             "token_url": "https://discord.com/api/oauth2/token",
             "scopes": ["bot", "messages.read"]},
    "capabilities": [
        {"id": "discord.messages.read", "description": "Read channel messages",
         "risk_level": "LOW"},
        {"id": "discord.messages.write", "description": "Send channel messages",
         "risk_level": "MEDIUM"},
    ],
    "actions": [
        {"id": "discord.send_message", "name": "Send message",
         "description": "Post a message to a channel.",
         "input_schema": schema("object", {
             "channel_id": {"type": "string"}, "content": {"type": "string"}},
             ["channel_id", "content"]),
         "required_capabilities": ["discord.messages.write"],
         "risk_level": "MEDIUM", "timeout_seconds": 30,
         "rate_limit_per_minute": 30,
         "verification": {"kind": "side_effect"}},
        {"id": "discord.get_channel", "name": "Get channel",
         "description": "Fetch channel metadata.",
         "input_schema": schema("object", {"channel_id": {"type": "string"}},
                                ["channel_id"]),
         "required_capabilities": ["discord.messages.read"],
         "risk_level": "LOW", "mutation": False},
    ],
    "triggers": [
        {"id": "discord.message.created", "name": "Message posted",
         "kind": "webhook", "event_types": ["message.created"]},
    ],
    "resources": [{"kind": "message", "provider_kind": "discord_message"}],
    "scopes": ["bot", "messages.read"],
    "rate_limits": {"per_minute": 30},
}

TELEGRAM_MANIFEST = {
    "id": "telegram",
    "name": "Telegram",
    "version": "1.0.0",
    "category": "communication",
    "type": "OFFICIAL",
    "trust": "VERIFIED",
    "description": "Telegram Bot API messaging.",
    "publisher": "OpenAgent",
    "license": "Apache-2.0",
    "documentation_url": "https://core.telegram.org/bots/api",
    "auth": {"type": "service_account"},
    "capabilities": [
        {"id": "telegram.messages.write", "description": "Send messages",
         "risk_level": "MEDIUM"},
        {"id": "telegram.messages.read", "description": "Read updates",
         "risk_level": "LOW"},
    ],
    "actions": [
        {"id": "telegram.send_message", "name": "Send message",
         "description": "Send a message to a chat.",
         "input_schema": schema("object", {
             "chat_id": {"type": "string"}, "text": {"type": "string"}},
             ["chat_id", "text"]),
         "required_capabilities": ["telegram.messages.write"],
         "risk_level": "MEDIUM", "timeout_seconds": 30,
         "rate_limit_per_minute": 30,
         "verification": {"kind": "side_effect"}},
        {"id": "telegram.get_me", "name": "Get bot identity",
         "description": "Verify the bot token and identity.",
         "input_schema": schema("object", {}),
         "required_capabilities": ["telegram.messages.read"],
         "risk_level": "LOW", "mutation": False},
    ],
    "triggers": [
        {"id": "telegram.message.created", "name": "Message received",
         "kind": "webhook", "event_types": ["message.created"]},
    ],
    "resources": [{"kind": "message", "provider_kind": "telegram_message"}],
    "scopes": [],
    "rate_limits": {"per_minute": 30},
}

MANIFESTS = {"discord": DISCORD_MANIFEST, "telegram": TELEGRAM_MANIFEST}
_DEFAULT_DISCORD = "https://discord.com/api/v10"
_DEFAULT_TELEGRAM = "https://api.telegram.org"


def _snowflake(value: str, what: str) -> str:
    if not value or not value.isdigit() or len(value) > 32:
        raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                            f"Invalid {what}")
    return value


async def execute(action_id: str, params: dict[str, Any],
                  auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    connector, _, short = action_id.partition(".")
    http = ctx["http"]
    if connector == "discord":
        base = base_url(auth, _DEFAULT_DISCORD)
        headers = bearer_headers(auth, scheme="Bot")
        if short == "send_message":
            schemas = _schema_of("discord.send_message")
            params = validate_input(schemas, params, action_id)
            channel = _snowflake(params["channel_id"], "channel_id")
            content = str(params.get("content", ""))
            if not content.strip() or len(content) > 2000:
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    "Content must be 1..2000 chars")
            resp = await http.request(
                "POST", f"{base}/channels/{channel}/messages",
                headers=headers, json_body={"content": content},
                timeout_seconds=30, max_attempts=2, idempotent=False)
            body = resp.body if isinstance(resp.body, dict) else {}
            return ok(action_id, {"id": body.get("id", "")},
                      provider_request_id=resp.provider_request_id, verified=True)
        if short == "get_channel":
            params = validate_input(_schema_of("discord.get_channel"), params,
                                    action_id)
            channel = _snowflake(params["channel_id"], "channel_id")
            resp = await http.request(
                "GET", f"{base}/channels/{channel}", headers=headers,
                timeout_seconds=30, max_attempts=3, idempotent=True)
            body = resp.body if isinstance(resp.body, dict) else {}
            return ok(action_id, {"id": body.get("id", ""),
                                  "name": body.get("name", ""),
                                  "type": body.get("type", "")},
                      provider_request_id=resp.provider_request_id, verified=True)
    if connector == "telegram":
        secrets = secrets_of(auth)
        token = secrets.get("bot_token") or secrets.get("api_key") or ""
        if not token or len(token) > 256 or any(c.isspace() for c in token):
            raise ProviderError(ProviderErrorKind.AUTHENTICATION_ERROR,
                                "Missing bot token")
        base = base_url(auth, _DEFAULT_TELEGRAM)
        # Bot token lives in the URL path (Telegram standard): never log it.
        safe_base = f"{base}/bot<redacted>"
        endpoint = f"{base}/bot{token}"
        if short == "send_message":
            params = validate_input(_schema_of("telegram.send_message"), params,
                                    action_id)
            text = str(params.get("text", ""))
            if not text.strip() or len(text) > 4096:
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    "Text must be 1..4096 chars")
            resp = await http.request(
                "POST", f"{endpoint}/sendMessage",
                json_body={"chat_id": params["chat_id"], "text": text},
                timeout_seconds=30, max_attempts=2, idempotent=False,
                log_url=f"{safe_base}/sendMessage")
            body = resp.body if isinstance(resp.body, dict) else {}
            if not body.get("ok"):
                raise ProviderError(ProviderErrorKind.PROVIDER_UNAVAILABLE,
                                    f"Telegram error: {body.get('description', '')[:200]}")
            result = body.get("result", {}) or {}
            return ok(action_id, {"message_id": result.get("message_id", "")},
                      verified=True)
        if short == "get_me":
            resp = await http.request(
                "GET", f"{endpoint}/getMe", timeout_seconds=15,
                max_attempts=2, idempotent=True,
                log_url=f"{safe_base}/getMe")
            body = resp.body if isinstance(resp.body, dict) else {}
            result = body.get("result", {}) or {}
            return ok(action_id, {"username": result.get("username", ""),
                                  "id": result.get("id", "")}, verified=True)
    raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                        f"Unknown action '{action_id}'")


async def test(auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    connector = str((ctx.get("connection", {}) or {}).get("connector_id", "")
                    or "telegram")
    if connector == "discord":
        http = ctx["http"]
        base = base_url(auth, _DEFAULT_DISCORD)
        headers = bearer_headers(auth, scheme="Bot")
        resp = await http.request("GET", f"{base}/users/@me", headers=headers,
                                  timeout_seconds=15, max_attempts=2,
                                  idempotent=True)
        body = resp.body if isinstance(resp.body, dict) else {}
        return {"provider": "discord", "username": body.get("username", "")}
    outcome = await execute("telegram.get_me", {}, auth, ctx)
    return {"provider": "telegram", **outcome.get("result", {})}


def normalize_event(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message", {}) if isinstance(payload, dict) else {}
    return {"event_type": "message.created",
            "resource_id": str(message.get("message_id", "")),
            "attributes": {"chat_id": str((message.get("chat") or {}).get("id", ""))}}


def _schema_of(action_id: str) -> dict[str, Any]:
    manifest = MANIFESTS.get(action_id.split(".", 1)[0], {})
    for action in manifest.get("actions", []):
        if action["id"] == action_id:
            return action["input_schema"]
    return {"type": "object"}
