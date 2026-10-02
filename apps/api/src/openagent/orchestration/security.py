"""Security helpers: secret redaction, output caps, prompt-injection framing."""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from openagent.orchestration.types import SECRET_KEY_HINTS

REDACTED = "[REDACTED]"

_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/=]{8,}", re.IGNORECASE)
_APIKEY_RE = re.compile(r"(api[_-]?key\s*[:=]\s*)(['\"]?)[A-Za-z0-9\-._~+/=]{8,}\2", re.IGNORECASE)
_SECRET_ASSIGN_RE = re.compile(
    r"((?:secret|password|token|private_key|client_secret)\s*[:=]\s*)(['\"]?)[^\s'\"]{4,}\2",
    re.IGNORECASE,
)


def contains_secret_key(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in SECRET_KEY_HINTS)


def sanitize_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy with secret-looking keys redacted (shallow + one nested level)."""
    cleaned: Dict[str, Any] = {}
    for key, value in payload.items():
        if contains_secret_key(str(key)):
            cleaned[key] = REDACTED
        elif isinstance(value, dict):
            cleaned[key] = {
                k: (REDACTED if contains_secret_key(str(k)) else v) for k, v in value.items()
            }
        elif isinstance(value, str):
            cleaned[key] = redact_text(value)
        else:
            cleaned[key] = value
    return cleaned


def redact_text(text: str) -> str:
    text = _BEARER_RE.sub(r"\1" + REDACTED, text)
    text = _APIKEY_RE.sub(r"\1\2" + REDACTED, text)
    text = _SECRET_ASSIGN_RE.sub(r"\1\2" + REDACTED, text)
    return text


def cap_output(output: Dict[str, Any], max_bytes: int) -> Dict[str, Any]:
    """Enforce output size limits; truncate oversized string leaves."""
    raw = json.dumps(output, default=str)
    if len(raw.encode("utf-8")) <= max_bytes:
        return output
    truncated: Dict[str, Any] = {}
    budget = max_bytes
    for key, value in output.items():
        chunk = json.dumps({key: value}, default=str)
        if len(chunk.encode("utf-8")) > budget and isinstance(value, str):
            allowed = max(0, budget - 64)
            truncated[key] = value[:allowed] + "...[TRUNCATED]"
            budget = 0
            break
        truncated[key] = value
        budget -= len(chunk.encode("utf-8"))
        if budget <= 0:
            break
    truncated["_truncated"] = True
    return truncated


def frame_untrusted(text: str) -> str:
    """Wrap model-generated instructions as untrusted data for downstream prompts."""
    return f"<untrusted-model-output>\n{text}\n</untrusted-model-output>"
