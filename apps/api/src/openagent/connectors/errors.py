"""Normalized provider errors (MP21).

Every connector maps provider failures into ProviderError kinds so policy,
retry, and audit layers behave consistently. Provider details are preserved
in a redacted debug field — never raw secrets.
"""

from __future__ import annotations

from typing import Any, Optional


class ProviderErrorKind(str):
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    CONFLICT = "CONFLICT"
    TIMEOUT = "TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"


class ProviderError(Exception):
    def __init__(self, kind: str, message: str, *,
                 status_code: Optional[int] = None,
                 retry_after_seconds: Optional[float] = None,
                 provider_code: str = "",
                 retryable_hint: Optional[bool] = None):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.provider_code = provider_code
        self.retryable_hint = retryable_hint

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": str(self),
                "status_code": self.status_code,
                "retry_after_seconds": self.retry_after_seconds,
                "provider_code": self.provider_code}


def normalize_http_error(status: int, body: Any,
                         provider_code: str = "") -> ProviderError:
    """Map HTTP status to a normalized kind. 4xx validation/auth failures
    are never retried blindly; 429/5xx/timeout may be."""
    text = str(body)[:300] if body else ""
    if status == 401:
        return ProviderError(ProviderErrorKind.AUTHENTICATION_ERROR,
                             f"Provider authentication failed. {text}",
                             status_code=status, provider_code=provider_code)
    if status == 403:
        return ProviderError(ProviderErrorKind.AUTHORIZATION_ERROR,
                             f"Provider authorization failed. {text}",
                             status_code=status, provider_code=provider_code)
    if status == 404:
        return ProviderError(ProviderErrorKind.NOT_FOUND,
                             f"Provider resource not found. {text}",
                             status_code=status, provider_code=provider_code)
    if status == 409:
        return ProviderError(ProviderErrorKind.CONFLICT,
                             f"Provider conflict. {text}",
                             status_code=status, provider_code=provider_code)
    if status == 422 or (400 <= status < 500 and status != 429):
        return ProviderError(ProviderErrorKind.VALIDATION_ERROR,
                             f"Provider rejected request: {text}",
                             status_code=status, provider_code=provider_code)
    if status == 429:
        return ProviderError(ProviderErrorKind.RATE_LIMITED,
                             "Provider rate limit exceeded",
                             status_code=status, provider_code=provider_code)
    if status in (502, 503, 504):
        return ProviderError(ProviderErrorKind.PROVIDER_UNAVAILABLE,
                             f"Provider unavailable ({status})",
                             status_code=status, provider_code=provider_code)
    if 500 <= status < 600:
        return ProviderError(ProviderErrorKind.PROVIDER_UNAVAILABLE,
                             f"Provider error ({status})",
                             status_code=status, provider_code=provider_code)
    return ProviderError(ProviderErrorKind.UNKNOWN_PROVIDER_ERROR,
                         f"Provider error ({status}): {text}",
                         status_code=status, provider_code=provider_code)


def normalize_exception(exc: BaseException) -> ProviderError:
    name = type(exc).__name__.lower()
    text = str(exc)[:300]
    if "timeout" in name or "timeout" in text.lower():
        return ProviderError(ProviderErrorKind.TIMEOUT,
                             f"Provider timeout: {text}")
    if "ssrf" in name.lower():
        # Re-raise SSRF blocks unwrapped: they are policy denials, not provider errors.
        raise exc
    return ProviderError(ProviderErrorKind.NETWORK_ERROR,
                         f"Provider network error: {text}")
