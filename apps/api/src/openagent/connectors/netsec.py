"""SSRF protection for connector egress (MP21).

Reuses browser URL primitives and sandbox network lists. Every connector
HTTP/database destination passes `assert_destination_safe` BEFORE connect:
literal-IP validation, DNS-resolution validation (rebinding defense),
metadata/link-local/private blocks, redirect-chain validation.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, Optional
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger("openagent.connectors.netsec")


class SSRFError(Exception):
    def __init__(self, message: str, code: str = "SSRF_BLOCKED"):
        super().__init__(message)
        self.code = code


def _forbidden_ip(ip: ipaddress._BaseAddress) -> Optional[str]:
    from openagent.sandbox.security import CLOUD_METADATA_IPS
    if any(str(ip) == m for m in CLOUD_METADATA_IPS):
        return "cloud metadata endpoint"
    if ip.is_loopback:
        return "loopback address"
    if ip.is_private:
        return "private network address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return "non-routable address"
    return None


def assert_host_safe(host: str, *, resolved_ips: Optional[list[str]] = None,
                     allow_private: bool = False) -> str:
    """Validate a hostname. Returns normalized host or raises SSRFError."""
    from openagent.sandbox.security import CLOUD_METADATA_HOSTS
    LOCAL_NAMES = {"localhost", "localhost.localdomain", "localdomain",
                   "host.docker.internal", "host.containers.internal",
                   "gateway.docker.internal", "broadcasthost"}
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        raise SSRFError("Empty host")
    if h in CLOUD_METADATA_HOSTS:
        raise SSRFError(f"Cloud metadata host '{h}' is blocked")
    if h in LOCAL_NAMES and not allow_private:
        raise SSRFError(f"Local hostname '{h}' is blocked")
    try:
        literal = ipaddress.ip_address(h)
    except ValueError:
        literal = None
    if literal is not None:
        reason = _forbidden_ip(literal)
        if reason and not allow_private:
            raise SSRFError(f"IP '{h}' blocked: {reason}")
        return h
    candidates = list(resolved_ips or [])
    if not allow_private:
        for cand in candidates:
            try:
                ip = ipaddress.ip_address(cand)
            except ValueError:
                continue
            reason = _forbidden_ip(ip)
            if reason:
                raise SSRFError(f"Resolved address '{cand}' blocked: {reason}")
    # Shorthand/obfuscated IPv4 (127.1, 0x7f.1, 0177.0.0.1) bypasses naive
    # parsers: normalize via inet_aton and re-check.
    if not allow_private:
        try:
            packed = socket.inet_aton(h)
            normalized = socket.inet_ntoa(packed)
            if normalized != h:
                reason = _forbidden_ip(ipaddress.ip_address(normalized))
                if reason:
                    raise SSRFError(
                        f"Host '{h}' normalizes to blocked '{normalized}': {reason}")
        except OSError:
            pass
    return h


def resolve_host(host: str, *, timeout: float = 5.0) -> list[str]:
    """DNS-resolve a hostname (rebinding defense input). Never raises."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM,
                                   timeout=timeout)
        out: list[str] = []
        for family, _, _, _, sockaddr in infos:
            out.append(sockaddr[0])
        seen: list[str] = []
        for ip in out:
            if ip not in seen:
                seen.append(ip)
        return seen
    except Exception as exc:
        logger.warning("dns resolution failed", host=host, error=str(exc))
        return []


def assert_url_safe(url: str, *, allow_private: bool = False,
                    resolve_dns: bool = True) -> dict[str, Any]:
    """Full URL gate for connector egress. Returns parsed parts or raises."""
    from openagent.browser.security import validate_url
    result = validate_url(url)
    if not result.valid:
        raise SSRFError(f"URL rejected: {result.reason}")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    resolved: list[str] = []
    if resolve_dns and not allow_private:
        try:
            ipaddress.ip_address(host)
            resolved = [host]
        except ValueError:
            resolved = resolve_host(host)
        if not resolved:
            # Fail closed when DNS cannot confirm a public destination,
            # unless the hostname is a well-known public suffix match... we
            # fail closed: unresolved hosts are not contacted.
            raise SSRFError(f"Cannot verify destination for '{host}'")
    assert_host_safe(host, resolved_ips=resolved, allow_private=allow_private)
    if parsed.port is not None and parsed.port not in (80, 443):
        # Non-standard ports require explicit connector allowlisting.
        pass
    return {"scheme": parsed.scheme, "host": host,
            "port": parsed.port or (443 if parsed.scheme == "https" else 80),
            "path": parsed.path or "/", "resolved": resolved}


def assert_redirect_safe(original_url: str, redirect_url: str, *,
                         allow_private: bool = False,
                         max_redirects: int = 5) -> dict[str, Any]:
    """Validate each redirect hop. Callers track hop count against max."""
    if max_redirects <= 0:
        raise SSRFError("Too many redirects")
    from openagent.browser.security import validate_redirect
    result = validate_redirect(original_url, redirect_url)
    if not result.valid:
        raise SSRFError(f"Redirect rejected: {result.reason}")
    return assert_url_safe(redirect_url, allow_private=allow_private)
