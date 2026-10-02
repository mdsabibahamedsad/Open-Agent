"""MP23: publisher-content validation + sanitization.

All publisher-controlled text (titles, descriptions, links, changelogs) is
untrusted. Rendered output must never execute scripts, and external links
must be opened safely. No HTML is accepted: descriptions use a small
markdown-lite subset rendered to escaped HTML by the frontend.
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse

_UNSAFE_SCHEMES = frozenset({"javascript", "data", "vbscript", "file", "blob"})

_SAFE_URL_RE = re.compile(r"^https?://[^\s<>\"]+$")

_EVENT_HANDLER_RE = re.compile(r"\bon\w+\s*=", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]*>")
_SCRIPT_BLOCK_RE = re.compile(
    r"<\s*(script|iframe|object|embed|form|style)\b.*?</\s*\1\s*>",
    re.IGNORECASE | re.DOTALL)
_SCRIPT_OPEN_RE = re.compile(
    r"<\s*(script|iframe|object|embed|form|style|link|meta)\b",
    re.IGNORECASE)
_UNSAFE_ATTR_URL_RE = re.compile(
    r"(?:href|src|xlink:href)\s*=\s*[\"']?\s*"
    r"(javascript|data|vbscript|file|blob)\s*:",
    re.IGNORECASE)

_MAX_TITLE = 255
_MAX_SHORT = 500
_MAX_BODY = 20000


class ContentError(ValueError):
    """Raised when publisher content is rejected (never silently altered)."""


def is_safe_url(url: str) -> bool:
    """Allow only http(s) URLs with a host; reject javascript:/data:/etc."""
    if not isinstance(url, str) or not url.strip():
        return False
    lowered = url.strip().lower()
    if lowered.startswith(("javascript:", "data:", "vbscript:", "file:", "blob:")):
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    return bool(_SAFE_URL_RE.match(url.strip()))


def check_url(url: str, *, field: str) -> None:
    if not is_safe_url(url):
        raise ContentError(f"{field}: URL must be an absolute http(s) URL")


def strip_html(text: str) -> str:
    """Remove all markup; used before storing titles/short text."""
    if not isinstance(text, str):
        return ""
    cleaned = _SCRIPT_BLOCK_RE.sub("", text)
    cleaned = _SCRIPT_OPEN_RE.sub("", cleaned)
    cleaned = _TAG_RE.sub("", cleaned)
    return html.unescape(cleaned).strip()


def contains_active_markup(text: str) -> bool:
    """Detect script-capable markup or event handlers in free text."""
    if not isinstance(text, str):
        return False
    return bool(_SCRIPT_BLOCK_RE.search(text) or _SCRIPT_OPEN_RE.search(text)
                or _EVENT_HANDLER_RE.search(text)
                or _UNSAFE_ATTR_URL_RE.search(text))


def validate_title(title: str) -> str:
    cleaned = strip_html(title)
    if not cleaned:
        raise ContentError("title: must not be empty")
    if len(cleaned) > _MAX_TITLE:
        raise ContentError(f"title: exceeds {_MAX_TITLE} characters")
    return cleaned


def validate_short_description(text: str) -> str:
    cleaned = strip_html(text)
    if len(cleaned) > _MAX_SHORT:
        raise ContentError(f"short_description: exceeds {_MAX_SHORT} characters")
    return cleaned


def validate_body(text: str, *, field: str = "description") -> str:
    """Validate long-form markdown-lite: no active markup, bounded size."""
    if not isinstance(text, str):
        raise ContentError(f"{field}: must be a string")
    if len(text) > _MAX_BODY:
        raise ContentError(f"{field}: exceeds {_MAX_BODY} characters")
    if contains_active_markup(text):
        raise ContentError(f"{field}: active markup/scripts are not allowed")
    return text


def validate_links(urls: list[str], *, field: str) -> list[str]:
    """Validate asset/link URL lists (screenshots, videos, docs)."""
    cleaned: list[str] = []
    for url in urls or []:
        if not isinstance(url, str) or not url.strip():
            continue
        check_url(url.strip(), field=field)
        if len(cleaned) >= 20:
            raise ContentError(f"{field}: at most 20 links allowed")
        cleaned.append(url.strip())
    return cleaned


def validate_listing_content(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalize listing display content. Returns clean copy."""
    out = dict(payload)
    if "title" in out:
        out["title"] = validate_title(str(out["title"]))
    if "short_description" in out:
        out["short_description"] = validate_short_description(
            str(out["short_description"]))
    if "full_description" in out:
        out["full_description"] = validate_body(str(out["full_description"]))
    for key in ("screenshots", "videos"):
        if key in out:
            values = out[key]
            if not isinstance(values, list):
                raise ContentError(f"{key}: must be a list of URLs")
            out[key] = validate_links([str(v) for v in values], field=key)
    for key in ("icon", "banner"):
        if out.get(key):
            check_url(str(out[key]), field=key)
    return out


def validate_review_text(title: str, body: str) -> tuple[str, str]:
    clean_title = strip_html(title or "")
    if len(clean_title) > 255:
        raise ContentError("review title exceeds 255 characters")
    clean_body = validate_body(body or "", field="review")
    if len(clean_body.strip()) < 10:
        raise ContentError("review: body must be at least 10 characters")
    return clean_title, clean_body
