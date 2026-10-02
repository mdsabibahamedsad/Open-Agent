"""Google Calendar + Google Drive official connectors (MP21)."""

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

CALENDAR_MANIFEST = {
    "id": "google_calendar",
    "name": "Google Calendar",
    "version": "1.0.0",
    "category": "productivity",
    "type": "OFFICIAL",
    "trust": "VERIFIED",
    "description": "Google Calendar events: list and create.",
    "publisher": "OpenAgent",
    "license": "Apache-2.0",
    "documentation_url": "https://developers.google.com/calendar/api",
    "auth": {"type": "oauth2",
             "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
             "token_url": "https://oauth2.googleapis.com/token",
             "scopes": ["https://www.googleapis.com/auth/calendar.readonly",
                        "https://www.googleapis.com/auth/calendar.events"]},
    "capabilities": [
        {"id": "google_calendar.events.read", "description": "List events",
         "risk_level": "LOW"},
        {"id": "google_calendar.events.write", "description": "Create events",
         "risk_level": "MEDIUM"},
    ],
    "actions": [
        {"id": "google_calendar.list_events", "name": "List events",
         "description": "List upcoming events on a calendar.",
         "input_schema": schema("object", {
             "calendar_id": {"type": "string"},
             "time_min": {"type": "string"},
             "max_results": {"type": "integer"}}),
         "required_capabilities": ["google_calendar.events.read"],
         "risk_level": "LOW", "mutation": False, "rate_limit_per_minute": 30},
        {"id": "google_calendar.create_event", "name": "Create event",
         "description": "Create a calendar event.",
         "input_schema": schema("object", {
             "calendar_id": {"type": "string"},
             "summary": {"type": "string"},
             "start": {"type": "string"}, "end": {"type": "string"},
             "description": {"type": "string"},
             "attendees": {"type": "array"}},
             ["summary", "start", "end"]),
         "required_capabilities": ["google_calendar.events.write"],
         "risk_level": "MEDIUM", "timeout_seconds": 30,
         "rate_limit_per_minute": 20,
         "verification": {"kind": "side_effect"}},
    ],
    "triggers": [],
    "resources": [{"kind": "calendar_event", "provider_kind": "event"}],
    "scopes": ["https://www.googleapis.com/auth/calendar.readonly",
               "https://www.googleapis.com/auth/calendar.events"],
    "rate_limits": {"per_minute": 30},
}

DRIVE_MANIFEST = {
    "id": "google_drive",
    "name": "Google Drive",
    "version": "1.0.0",
    "category": "productivity",
    "type": "OFFICIAL",
    "trust": "VERIFIED",
    "description": "Google Drive files: list, download metadata, upload.",
    "publisher": "OpenAgent",
    "license": "Apache-2.0",
    "documentation_url": "https://developers.google.com/drive/api",
    "auth": {"type": "oauth2",
             "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
             "token_url": "https://oauth2.googleapis.com/token",
             "scopes": ["https://www.googleapis.com/auth/drive.readonly",
                        "https://www.googleapis.com/auth/drive.file"]},
    "capabilities": [
        {"id": "google_drive.files.read", "description": "List/read file metadata",
         "risk_level": "LOW"},
        {"id": "google_drive.files.write", "description": "Upload files",
         "risk_level": "MEDIUM"},
    ],
    "actions": [
        {"id": "google_drive.list_files", "name": "List files",
         "description": "Search files by query.",
         "input_schema": schema("object", {
             "q": {"type": "string"}, "page_size": {"type": "integer"}}),
         "required_capabilities": ["google_drive.files.read"],
         "risk_level": "LOW", "mutation": False, "rate_limit_per_minute": 30},
        {"id": "google_drive.get_file", "name": "Get file metadata",
         "description": "Fetch metadata for one file.",
         "input_schema": schema("object", {"file_id": {"type": "string"}},
                                ["file_id"]),
         "required_capabilities": ["google_drive.files.read"],
         "risk_level": "LOW", "mutation": False, "rate_limit_per_minute": 30},
        {"id": "google_drive.upload_file", "name": "Upload file",
         "description": "Multipart upload (size-capped, type-checked).",
         "input_schema": schema("object", {
             "name": {"type": "string"}, "mime_type": {"type": "string"},
             "content_base64": {"type": "string"},
             "parent_id": {"type": "string"}}, ["name", "content_base64"]),
         "required_capabilities": ["google_drive.files.write"],
         "risk_level": "MEDIUM", "timeout_seconds": 120,
         "rate_limit_per_minute": 10,
         "verification": {"kind": "side_effect"}},
    ],
    "triggers": [
        {"id": "google_drive.file.created", "name": "File created",
         "kind": "polling",
         "poll_config": {"interval_seconds": 300},
         "description": "Poll for new files (Drive push needs GCP channel)."},
    ],
    "resources": [
        {"kind": "file", "provider_kind": "drive_file"},
        {"kind": "document", "provider_kind": "drive_doc"},
    ],
    "scopes": ["https://www.googleapis.com/auth/drive.readonly",
               "https://www.googleapis.com/auth/drive.file"],
    "rate_limits": {"per_minute": 30},
}

MANIFESTS = {"google_calendar": CALENDAR_MANIFEST, "google_drive": DRIVE_MANIFEST}
_DEFAULT_CAL = "https://www.googleapis.com/calendar/v3"
_DEFAULT_DRIVE = "https://www.googleapis.com/drive/v3"
_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"

_ALLOWED_UPLOAD_TYPES = {"text/plain", "text/csv", "application/json",
                         "application/pdf", "image/png", "image/jpeg",
                         "text/markdown"}
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


async def execute(action_id: str, params: dict[str, Any],
                  auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    connector, _, short = action_id.partition(".")
    http = ctx["http"]
    headers = bearer_headers(auth)
    if connector == "google_calendar":
        base = base_url(auth, _DEFAULT_CAL)
        if short == "list_events":
            params = validate_input(_schema_of(action_id), params, action_id)
            query: dict[str, Any] = {
                "maxResults": min(int(params.get("max_results", 20) or 20), 100),
                "singleEvents": "true", "orderBy": "startTime"}
            if params.get("time_min"):
                query["timeMin"] = params["time_min"]
            calendar = params.get("calendar_id", "primary") or "primary"
            resp = await http.request(
                "GET", f"{base}/calendars/{calendar}/events", headers=headers,
                params=query, timeout_seconds=30, max_attempts=3, idempotent=True)
            body = resp.body if isinstance(resp.body, dict) else {}
            items = body.get("items", []) or []
            return ok(action_id, {"events": [
                {"id": e.get("id"), "summary": e.get("summary", ""),
                 "start": (e.get("start") or {}).get("dateTime", ""),
                 "end": (e.get("end") or {}).get("dateTime", ""),
                 "htmlLink": e.get("htmlLink", "")} for e in items
                if isinstance(e, dict)]},
                provider_request_id=resp.provider_request_id, verified=True)
        if short == "create_event":
            params = validate_input(_schema_of(action_id), params, action_id)
            calendar = params.get("calendar_id", "primary") or "primary"
            attendees = params.get("attendees", []) or []
            if not isinstance(attendees, list) or len(attendees) > 50:
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    "Attendees must be a list of <= 50")
            resp = await http.request(
                "POST", f"{base}/calendars/{calendar}/events", headers=headers,
                json_body={"summary": params["summary"],
                           "description": params.get("description", ""),
                           "start": {"dateTime": params["start"]},
                           "end": {"dateTime": params["end"]},
                           "attendees": [{"email": a} for a in attendees
                                         if isinstance(a, str)]},
                timeout_seconds=30, max_attempts=2, idempotent=False)
            body = resp.body if isinstance(resp.body, dict) else {}
            return ok(action_id, {"id": body.get("id", ""),
                                  "htmlLink": body.get("htmlLink", "")},
                      provider_request_id=resp.provider_request_id, verified=True)
    if connector == "google_drive":
        base = base_url(auth, _DEFAULT_DRIVE)
        if short == "list_files":
            params = validate_input(_schema_of(action_id), params, action_id)
            query: dict[str, Any] = {
                "pageSize": min(int(params.get("page_size", 20) or 20), 100),
                "fields": "files(id,name,mimeType,size,parents)"}
            if params.get("q"):
                query["q"] = params["q"]
            resp = await http.request(
                "GET", f"{base}/files", headers=headers, params=query,
                timeout_seconds=30, max_attempts=3, idempotent=True)
            body = resp.body if isinstance(resp.body, dict) else {}
            return ok(action_id, {"files": body.get("files", []) or []},
                      provider_request_id=resp.provider_request_id, verified=True)
        if short == "get_file":
            params = validate_input(_schema_of(action_id), params, action_id)
            file_id = "".join(c for c in params["file_id"]
                              if c.isalnum() or c in "-_")
            if not file_id:
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    "Invalid file id")
            resp = await http.request(
                "GET", f"{base}/files/{file_id}", headers=headers,
                params={"fields": "id,name,mimeType,size,parents,webViewLink"},
                timeout_seconds=30, max_attempts=3, idempotent=True)
            body = resp.body if isinstance(resp.body, dict) else {}
            return ok(action_id, body,
                      provider_request_id=resp.provider_request_id, verified=True)
        if short == "upload_file":
            import base64
            params = validate_input(_schema_of(action_id), params, action_id)
            mime = str(params.get("mime_type", "text/plain"))
            if mime not in _ALLOWED_UPLOAD_TYPES:
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    f"Upload MIME '{mime}' not allowed")
            try:
                content = base64.b64decode(params["content_base64"])
            except Exception as exc:
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    "content_base64 is not valid base64") from exc
            if len(content) > _MAX_UPLOAD_BYTES:
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    "Upload exceeds 10 MiB cap")
            name = str(params.get("name", "upload"))
            if "/" in name or "\\" in name or not name.strip():
                raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                                    "Invalid file name")
            metadata = {"name": name}
            if params.get("parent_id"):
                metadata["parents"] = [params["parent_id"]]
            import json as _json
            boundary = "oa" + "x" * 16
            head = (_json.dumps(metadata)).encode()
            body_bytes = (f"--{boundary}\r\nContent-Type: application/json\r\n\r\n".encode()
                          + head + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode()
                          + content + f"\r\n--{boundary}--".encode())
            up_headers = dict(headers)
            up_headers["Content-Type"] = f"multipart/related; boundary={boundary}"
            resp = await http.request(
                "POST", f"{_UPLOAD_BASE}/files?uploadType=multipart",
                headers=up_headers, form=body_bytes,
                timeout_seconds=120, max_attempts=2, idempotent=False)
            result = resp.body if isinstance(resp.body, dict) else {}
            return ok(action_id, {"id": result.get("id", ""),
                                  "name": result.get("name", "")},
                      provider_request_id=resp.provider_request_id, verified=True)
    raise ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                        f"Unknown action '{action_id}'")


async def test(auth: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    http = ctx["http"]
    headers = bearer_headers(auth)
    resp = await http.request("GET", "https://www.googleapis.com/oauth2/v3/userinfo",
                              headers=headers, timeout_seconds=15,
                              max_attempts=2, idempotent=True)
    body = resp.body if isinstance(resp.body, dict) else {}
    return {"provider": "google", "email": body.get("email", "")}


def normalize_event(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"event_type": event or "file.created",
            "resource_id": str(payload.get("id", "")),
            "attributes": {}}


def _schema_of(action_id: str) -> dict[str, Any]:
    manifest = MANIFESTS.get(action_id.split(".", 1)[0], {})
    for action in manifest.get("actions", []):
        if action["id"] == action_id:
            return action["input_schema"]
    return {"type": "object"}
