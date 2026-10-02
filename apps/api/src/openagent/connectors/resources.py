"""Normalized external resources (MP21).

Provider payloads normalize into these shapes (normalized core + provider
metadata). Every record keeps provider/provider_id/raw_reference.
"""

from __future__ import annotations

from typing import Any


def _base(kind: str, provider: str, provider_id: str,
          raw: dict[str, Any]) -> dict[str, Any]:
    return {"kind": kind, "provider": provider, "provider_id": str(provider_id),
            "raw_reference": {"provider": provider, "id": str(provider_id),
                              "snapshot": {k: v for k, v in (raw or {}).items()
                                           if k not in ("_raw",) }}}


def normalize_user(provider: str, raw: dict[str, Any]) -> dict[str, Any]:
    record = _base("user", provider,
                   raw.get("id") or raw.get("login") or raw.get("email") or "", raw)
    record.update({"name": raw.get("name") or raw.get("login") or "",
                   "email": raw.get("email", ""),
                   "username": raw.get("login") or raw.get("username", "")})
    return record


def normalize_message(provider: str, raw: dict[str, Any]) -> dict[str, Any]:
    record = _base("message", provider, raw.get("id") or raw.get("ts") or "", raw)
    record.update({"channel": raw.get("channel") or raw.get("channel_id", ""),
                   "author": raw.get("user") or raw.get("from", ""),
                   "text": raw.get("text") or raw.get("body", ""),
                   "timestamp": raw.get("ts") or raw.get("created_at", "")})
    return record


def normalize_file(provider: str, raw: dict[str, Any]) -> dict[str, Any]:
    record = _base("file", provider, raw.get("id", ""), raw)
    record.update({"name": raw.get("name", ""),
                   "mime_type": raw.get("mimeType") or raw.get("mime_type", ""),
                   "size_bytes": raw.get("size", 0),
                   "parent_id": raw.get("parent_id") or
                   ((raw.get("parents") or [None])[0])})
    return record


def normalize_task(provider: str, raw: dict[str, Any]) -> dict[str, Any]:
    record = _base("task", provider, raw.get("id", ""), raw)
    record.update({"title": raw.get("title") or raw.get("name", ""),
                   "status": raw.get("status", ""),
                   "assignee": raw.get("assignee", "")})
    return record


def normalize_repository(provider: str, raw: dict[str, Any]) -> dict[str, Any]:
    record = _base("repository", provider,
                   raw.get("id") or raw.get("full_name", ""), raw)
    record.update({"full_name": raw.get("full_name", ""),
                   "html_url": raw.get("html_url") or raw.get("web_url", ""),
                   "default_branch": raw.get("default_branch", "")})
    return record


def normalize_document(provider: str, raw: dict[str, Any]) -> dict[str, Any]:
    record = _base("document", provider, raw.get("id", ""), raw)
    record.update({"title": raw.get("title") or raw.get("name", ""),
                   "url": raw.get("url") or raw.get("webViewLink", "")})
    return record


NORMALIZERS = {
    "user": normalize_user,
    "message": normalize_message,
    "file": normalize_file,
    "task": normalize_task,
    "repository": normalize_repository,
    "document": normalize_document,
}


def normalize(kind: str, provider: str, raw: dict[str, Any]) -> dict[str, Any]:
    normalizer = NORMALIZERS.get((kind or "").lower())
    if normalizer is None:
        record = _base(kind or "unknown", provider, (raw or {}).get("id", ""), raw or {})
        record["attributes"] = dict(raw or {})
        return record
    return normalizer(provider, raw or {})
