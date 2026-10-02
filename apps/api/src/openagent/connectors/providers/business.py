"""Notion + HubSpot official connectors (MP21)."""

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

NOTION_MANIFEST = {
    "id": "notion",
    "name": "Notion",
    "version": "1.0.0",
    "category": "productivity",
    "type": "OFFICIAL",
    "trust": "VERIFIED",
    "description": "Notion pages and databases.",
    "publisher": "OpenAgent",
    "license": "Apache-2.0",
    "documentation_url": "https://developers.notion.com/",
    "auth": {"type": "oauth2",
             "authorize_url": "https://api.notion.com/v1/oauth/authorize",
             "token_url": "https://api.notion.com/v1/oauth/token",
             "scopes": []},
    "capabilities": [
        {"id": "notion.pages.read", "description": "Read pages",
         "risk_level": "LOW"},
        {"id": "notion.pages.write", "description": "Create pages",
         "risk_level": "MEDIUM"},
        {"id": "notion.databases.read", "description": "Query databases",
         "risk_level": "LOW"},
    ],
    "actions": [
        {"id": "notion.create_page", "name": "Create page",
         "description": "Create a page in a database or as a child page.",
         "input_schema": schema("object", {
             "parent_id": {"type": "string"}, "title": {"type": "string"},
             "content": {"type": "string"}}, ["parent_id", "title"]),
         "required_capabilities": ["notion.pages.write"],
         "risk_level": "MEDIUM", "timeout_seconds": 30,
         "rate_limit_per_minute": 20,
         "verification": {"kind": "side_effect"}},
        {"id": "notion.get_page", "name": "Get page",
         "description": "Fetch a page by id.",
         "input_schema": schema("object", {"page_id": {"type": "string"}},
                                ["page_id"]),
         "required_capabilities": ["notion.pages.read"],
         "risk_level": "LOW", "mutation": False},
        {"id": "notion.query_database", "name": "Query database",
         "description": "Query a database with an optional filter.",
         "input_schema": schema("object", {
             "database_id": {"type": "string"},
             "filter": {"type": "object"},
             "page_size": {"type": "integer"}}, ["database_id"]),
         "required_capabilities": ["notion.databases.read"],
         "risk_level": "LOW", "mutation": False, "rate_limit_per_minute": 20},
    ],
    "triggers": [],
    "resources": [
        {"kind": "document", "provider_kind": "notion_page"},
        {"kind": "task", "provider_kind": "notion_row"},
    ],
    "scopes": [],
    "rate_limits": {"per_minute": 20},
}

HUBSPOT_MANIFEST = {
    "id": "hubspot",
    "name": "HubSpot",
    "version": "1.0.0",
    "category": "crm",
    "type": "OFFICIAL",
    "trust": "VERIFIED",
    "description": "HubSpot contacts and tickets.",
    "publisher": "OpenAgent",
    "license": "Apache-2.0",
    "documentation_url": "https://developers.hubspot.com/docs/api/overview",
    "auth": {"type": "oauth2",
             "authorize_url": "https://app.hubspot.com/oauth/authorize",
             "token_url": "https://api.hubapi.com/oauth/v1/token",
             "scopes": ["crm.objects.contacts.read", "crm.objects.contacts.write",
                        "tickets"]},
    "capabilities": [
        {"id": "hubspot.contacts.read", "description": "Read contacts",
         "risk_level": "LOW"},
        {"id": "hubspot.contacts.write", "description": "Create contacts",
         "risk_level": "MEDIUM"},
        {"id": "hubspot.tickets.write", "description": "Create tickets",
         "risk_level": "MEDIUM"},
    ],
    "actions": [
        {"id": "hubspot.create_contact", "name": "Create contact",
         "description": "Create a CRM contact.",
         "input_schema": schema("object", {
             "email": {"type": "string"},
             "firstname": {"type": "string"},
             "lastname": {"type": "string"},
             "company": {"type": "string"}}, ["email"]),
         "required_capabilities": ["hubspot.contacts.write"],
         "risk_level": "MEDIUM", "timeout_seconds": 30,
         "rate_limit_per_minute": 30,
         "verification": {"kind": "side_effect"}},
        {"id": "hubspot.get_contact", "name": "Get contact",
         "description": "Fetch a contact by id.",
         "input_schema": schema("object", {"contact_id": {"type": "string"}},
                                ["contact_id"]),
         "required_capabilities": ["hubspot.contacts.read"],
         "risk_level": "LOW", "mutation": False},
        {"id": "hubspot.list_contacts", "name": "List contacts",
         "description": "List recently updated contacts.",
         "input_schema": schema("object", {"limit": {"type": "integer"}}),
         "required_capabilities": ["hubspot.contacts.read"],
         "risk_level": "LOW", "mutation": False, "rate_limit_per_minute": 30},
        {"id": "hubspot.create_ticket", "name": "Create ticket",
         "description": "Create a support ticket.",
         "input_schema": schema("object", {
             "subject": {"type": "string"},
             "content": {"type": "string"},
             "pipeline": {"type": "string"}}, ["subject"]),
         "required_capabilities": ["hubspot.tickets.write"],
         "risk_level": "MEDIUM", "timeout_seconds": 30,
         "rate_limit_per_minute": 20,
         "verification": {"kind": "side_effect"}},
    ],
    "triggers": [
        {"id": "hubspot.contact.created", "name": "Contact created",
         "kind": "webhook", "event_types": ["contact.created"]},
        {"id": "hubspot.ticket.created", "name": "Ticket created",
         "kind": "webhook", "event_types": ["ticket.created"]},
    ],
    "resources": [
        {"kind": "customer", "provider_kind": "hubspot_contact"},
        {"kind": "ticket", "provider_kind": "hubspot_ticket"},
    ],
    "scopes": ["crm.objects.contacts.read", "crm.objects.contacts.write",
               "tickets"],
    "rate_limits": {"per_minute": 30},
}

MANIFESTS = {"notion": NOTION_MANIFEST, "hubspot": HUBSPOT_MANIFEST}
_DEFAULT_NOTION = "https://api.notion.com/v1"
_DEFAULT_HUBSPOT = "https://api.hubapi.com"


def _notion_id(value: str, what: str) -> str:
    cleaned = "".join(c for c in (value or "") if c.isalnum() or c == "-")
    if len(cleaned) not in (32, 36):
        raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                            f"Invalid {what}")
    return cleaned


async def execute(action_id: str, params: dict[str, Any],
                  auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    connector, _, short = action_id.partition(".")
    http = ctx["http"]
    if connector == "notion":
        base = base_url(auth, _DEFAULT_NOTION)
        headers = bearer_headers(
            auth, extra={"Notion-Version": "2022-06-28",
                         "Content-Type": "application/json"})
        if short == "create_page":
            params = validate_input(_schema_of(action_id), params, action_id)
            parent = _notion_id(params["parent_id"], "parent_id")
            title = str(params.get("title", ""))[:500]
            if not title.strip():
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    "Title required")
            blocks = []
            content = str(params.get("content", ""))[:8000]
            if content.strip():
                blocks = [{"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": [
                               {"type": "text",
                                "text": {"content": content[:2000]}}]}}]
            resp = await http.request(
                "POST", f"{base}/pages", headers=headers,
                json_body={"parent": {"page_id": parent},
                           "properties": {"title": {"title": [
                               {"text": {"content": title}}]}},
                           "children": blocks},
                timeout_seconds=30, max_attempts=2, idempotent=False)
            body = resp.body if isinstance(resp.body, dict) else {}
            return ok(action_id, {"id": body.get("id", ""),
                                  "url": body.get("url", "")},
                      provider_request_id=resp.provider_request_id, verified=True)
        if short == "get_page":
            params = validate_input(_schema_of(action_id), params, action_id)
            page = _notion_id(params["page_id"], "page_id")
            resp = await http.request(
                "GET", f"{base}/pages/{page}", headers=headers,
                timeout_seconds=30, max_attempts=3, idempotent=True)
            body = resp.body if isinstance(resp.body, dict) else {}
            return ok(action_id, {"id": body.get("id", ""),
                                  "url": body.get("url", "")},
                      provider_request_id=resp.provider_request_id, verified=True)
        if short == "query_database":
            params = validate_input(_schema_of(action_id), params, action_id)
            database = _notion_id(params["database_id"], "database_id")
            filt = params.get("filter", {}) or {}
            if not isinstance(filt, dict):
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    "filter must be an object")
            resp = await http.request(
                "POST", f"{base}/databases/{database}/query", headers=headers,
                json_body={"filter": filt,
                           "page_size": min(int(params.get("page_size", 20) or 20),
                                            100)},
                timeout_seconds=30, max_attempts=3, idempotent=True)
            body = resp.body if isinstance(resp.body, dict) else {}
            return ok(action_id, {"results": body.get("results", []) or [],
                                  "has_more": bool(body.get("has_more", False))},
                      provider_request_id=resp.provider_request_id, verified=True)
    if connector == "hubspot":
        base = base_url(auth, _DEFAULT_HUBSPOT)
        headers = bearer_headers(auth)
        if short == "create_contact":
            params = validate_input(_schema_of(action_id), params, action_id)
            email = str(params.get("email", ""))
            if "@" not in email or len(email) > 320:
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    "Invalid email")
            props = {k: params[k] for k in ("email", "firstname", "lastname",
                                            "company") if params.get(k)}
            resp = await http.request(
                "POST", f"{base}/crm/v3/objects/contacts", headers=headers,
                json_body={"properties": props},
                timeout_seconds=30, max_attempts=2, idempotent=True)
            body = resp.body if isinstance(resp.body, dict) else {}
            return ok(action_id, {"id": body.get("id", "")},
                      provider_request_id=resp.provider_request_id, verified=True)
        if short == "get_contact":
            params = validate_input(_schema_of(action_id), params, action_id)
            contact = "".join(c for c in params["contact_id"] if c.isalnum())
            if not contact:
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    "Invalid contact id")
            resp = await http.request(
                "GET", f"{base}/crm/v3/objects/contacts/{contact}",
                headers=headers,
                params={"properties": "email,firstname,lastname,company"},
                timeout_seconds=30, max_attempts=3, idempotent=True)
            body = resp.body if isinstance(resp.body, dict) else {}
            return ok(action_id, {"id": body.get("id", ""),
                                  "properties": body.get("properties", {}) or {}},
                      provider_request_id=resp.provider_request_id, verified=True)
        if short == "list_contacts":
            params = validate_input(_schema_of(action_id), params, action_id)
            resp = await http.request(
                "GET", f"{base}/crm/v3/objects/contacts", headers=headers,
                params={"limit": min(int(params.get("limit", 20) or 20), 100),
                        "properties": "email,firstname,lastname"},
                timeout_seconds=30, max_attempts=3, idempotent=True)
            body = resp.body if isinstance(resp.body, dict) else {}
            return ok(action_id, {"results": body.get("results", []) or []},
                      provider_request_id=resp.provider_request_id, verified=True)
        if short == "create_ticket":
            params = validate_input(_schema_of(action_id), params, action_id)
            resp = await http.request(
                "POST", f"{base}/crm/v3/objects/tickets", headers=headers,
                json_body={"properties": {
                    "subject": str(params.get("subject", ""))[:500],
                    "content": str(params.get("content", ""))[:4000],
                    "hs_pipeline": params.get("pipeline", "0")}},
                timeout_seconds=30, max_attempts=2, idempotent=True)
            body = resp.body if isinstance(resp.body, dict) else {}
            return ok(action_id, {"id": body.get("id", "")},
                      provider_request_id=resp.provider_request_id, verified=True)
    raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                        f"Unknown action '{action_id}'")


async def test(auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    http = ctx["http"]
    connector = str((ctx.get("connection", {}) or {}).get("connector_id", "")
                    or "notion")
    if connector == "hubspot":
        base = base_url(auth, _DEFAULT_HUBSPOT)
        headers = bearer_headers(auth)
        resp = await http.request(
            "GET", f"{base}/crm/v3/objects/contacts", headers=headers,
            params={"limit": 1}, timeout_seconds=15, max_attempts=2,
            idempotent=True)
        return {"provider": "hubspot", "ok": True}
    base = base_url(auth, _DEFAULT_NOTION)
    headers = bearer_headers(auth, extra={"Notion-Version": "2022-06-28"})
    resp = await http.request("GET", f"{base}/users/me", headers=headers,
                              timeout_seconds=15, max_attempts=2, idempotent=True)
    body = resp.body if isinstance(resp.body, dict) else {}
    return {"provider": "notion", "id": body.get("id", "")}


def normalize_event(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"event_type": event, "resource_id": str(payload.get("objectId", "")),
            "attributes": {"subscription": str(payload.get("subscriptionId", ""))}}


def _schema_of(action_id: str) -> dict[str, Any]:
    manifest = MANIFESTS.get(action_id.split(".", 1)[0], {})
    for action in manifest.get("actions", []):
        if action["id"] == action_id:
            return action["input_schema"]
    return {"type": "object"}
