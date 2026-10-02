"""Browser security: URL validation (SSRF), domain policies, redaction, prompt-injection defense, risk."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_SCHEMES = {"file", "ftp", "javascript", "data", "blob", "chrome", "devtools",
                   "chrome-extension", "moz-extension", "view-source", "about"}
BLOCKED_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}
CLOUD_METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal", "metadata.google.com",
                        "metadata.azure.com", "metadata.aws.internal"}
CLOUD_METADATA_PREFIXES = ("http://169.254.169.254", "http://metadata.google.internal",
                           "http://metadata.azure.com")
UNSAFE_PORTS = {22, 23, 25, 110, 143, 3306, 5432, 6379, 6380, 27017, 11211}

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"reveal\s+(your\s+)?(system\s+prompt|instructions|secret)",
    r"send\s+(secrets?|cookies?|passwords?|tokens?|credentials?)\s+to\b",
    r"transfer\s+(money|funds)\b",
    r"delete\s+(all\s+)?(data|database|files)\b",
    r"disable\s+(security|safety|guardrails?)\b",
    r"you\s+are\s+now\s+(in\s+)?(developer|admin|root|god)\s+mode",
    r"exfiltrate\b",
    r"\bjavascript\s*:",
]

SENSITIVE_KEYS = {"password", "passwd", "secret", "api_key", "apikey", "token",
                  "access_token", "refresh_token", "session", "cookie", "auth",
                  "authorization", "private_key", "client_secret", "credit_card",
                  "card_number", "cvv", "ssn"}
SENSITIVE_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|"
    r"(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)

ACTION_RISK: dict[str, str] = {
    "NAVIGATE": "MEDIUM", "CLICK": "MEDIUM", "DOUBLE_CLICK": "MEDIUM",
    "TYPE": "MEDIUM", "FILL": "MEDIUM", "SELECT": "MEDIUM", "CHECK": "MEDIUM",
    "UNCHECK": "MEDIUM", "HOVER": "LOW", "SCROLL": "LOW", "PRESS_KEY": "MEDIUM",
    "DRAG": "MEDIUM", "DROP": "MEDIUM", "WAIT": "LOW", "SCREENSHOT": "LOW",
    "EXTRACT": "LOW", "UPLOAD": "HIGH", "DOWNLOAD": "MEDIUM", "SWITCH_TAB": "LOW",
    "GO_BACK": "LOW", "GO_FORWARD": "LOW", "RELOAD": "LOW", "FOCUS": "LOW",
    "EVALUATE": "HIGH", "SET_VIEWPORT": "LOW", "SET_COOKIE": "MEDIUM",
    "CLEAR_COOKIES": "MEDIUM", "GET_COOKIES": "LOW", "AUTHENTICATE": "CRITICAL",
    "HANDLE_DIALOG": "MEDIUM", "WAIT_FOR_SELECTOR": "LOW", "WAIT_FOR_NAVIGATION": "LOW",
    "WAIT_FOR_FUNCTION": "LOW", "SELECT_OPTION": "MEDIUM", "SET_INPUT_FILES": "HIGH",
    "CHECKBOX": "MEDIUM", "RADIO": "MEDIUM",
}
APPROVAL_REQUIRED = {"UPLOAD", "AUTHENTICATE", "EVALUATE", "SET_INPUT_FILES"}
RETRY_SAFE = {"HOVER", "SCROLL", "SCREENSHOT", "EXTRACT", "WAIT", "GO_BACK",
              "GO_FORWARD", "RELOAD", "FOCUS", "WAIT_FOR_SELECTOR",
              "WAIT_FOR_NAVIGATION", "WAIT_FOR_FUNCTION", "GET_COOKIES"}
NON_RETRYABLE_DESTRUCTIVE = {"CLICK", "DOUBLE_CLICK", "TYPE", "FILL", "SELECT",
                             "UPLOAD", "AUTHENTICATE", "EVALUATE", "SET_INPUT_FILES",
                             "DRAG", "DROP", "PRESS_KEY"}


@dataclass
class URLValidationResult:
    valid: bool
    reason: str = ""
    sanitized_url: Optional[str] = None
    policy_action: str = "ALLOW"


def _is_blocked_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    if ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        return True
    if isinstance(ip, ipaddress.IPv4Address):
        return ip.is_private
    # IPv6 unique-local / link-local already covered; block ULA explicitly
    return ip.is_private


def _matches_domain(hostname: str, policy_domain: str) -> bool:
    h = hostname.lower().strip(".")
    p = policy_domain.lower().strip(".")
    if h == p:
        return True
    if p.startswith("*."):
        suffix = p[2:]
        return h == suffix or h.endswith("." + suffix)
    if p.startswith("."):
        suffix = p[1:]
        return h == suffix or h.endswith("." + suffix)
    return False


def validate_url(url: str, domain_policies: Optional[list[dict[str, Any]]] = None) -> URLValidationResult:
    """Fail-closed URL validation: SSRF, private IPs, metadata, unsafe schemes/ports."""
    url = (url or "").strip()
    if not url:
        return URLValidationResult(valid=False, reason="Empty URL")
    if len(url) > 2048:
        return URLValidationResult(valid=False, reason="URL too long")
    try:
        parsed = urlparse(url)
    except Exception as exc:
        return URLValidationResult(valid=False, reason=f"Invalid URL: {exc}")
    scheme = parsed.scheme.lower()
    if scheme in BLOCKED_SCHEMES or scheme not in ALLOWED_SCHEMES:
        return URLValidationResult(valid=False, reason=f"Scheme '{scheme or '(none)'}' is not allowed")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return URLValidationResult(valid=False, reason="URL has no host")
    # DNS-rebinding / lookalike hygiene: reject userinfo, whitespace, control chars
    if parsed.username or parsed.password:
        return URLValidationResult(valid=False, reason="URLs with credentials are not allowed")
    if re.search(r"[\s\x00-\x1f\x7f]", url):
        return URLValidationResult(valid=False, reason="URL contains illegal characters")
    if hostname in BLOCKED_HOSTNAMES:
        return URLValidationResult(valid=False, reason=f"Host '{hostname}' is blocked")
    if hostname in CLOUD_METADATA_HOSTS or url.lower().startswith(CLOUD_METADATA_PREFIXES):
        return URLValidationResult(valid=False, reason="Cloud metadata endpoints are blocked")
    if _is_blocked_ip(hostname):
        return URLValidationResult(valid=False, reason=f"IP '{hostname}' is in a blocked range")
    try:
        port = parsed.port
    except ValueError:
        return URLValidationResult(valid=False, reason="Invalid port in URL")
    if port is not None and port in UNSAFE_PORTS:
        return URLValidationResult(valid=False, reason=f"Port {port} is blocked")
    if re.search(r"^0x[0-9a-f]+$", hostname) or re.fullmatch(r"\d+", hostname):
        return URLValidationResult(valid=False, reason="Obfuscated numeric hosts are blocked")
    action = evaluate_domain_policy(hostname, domain_policies or [])
    if action == "DENY":
        return URLValidationResult(valid=False, reason=f"Domain '{hostname}' is denied by policy", policy_action="DENY")
    if action == "CONFIRM":
        return URLValidationResult(valid=True, reason="Domain requires confirmation",
                                   sanitized_url=sanitize_url(url), policy_action="CONFIRM")
    return URLValidationResult(valid=True, sanitized_url=sanitize_url(url), policy_action="ALLOW")


def validate_redirect(original_url: str, redirect_url: str,
                      domain_policies: Optional[list[dict[str, Any]]] = None) -> URLValidationResult:
    result = validate_url(redirect_url, domain_policies)
    if not result.valid:
        result.reason = f"Redirect blocked: {result.reason}"
    return result


def evaluate_domain_policy(hostname: str, policies: list[dict[str, Any]]) -> str:
    """Most-specific (longest domain, then highest priority) policy wins. Default ALLOW."""
    best: Optional[dict[str, Any]] = None
    best_key: tuple[int, int] = (-1, -1)
    for p in policies:
        domain = str(p.get("domain", ""))
        if not domain or not _matches_domain(hostname, domain):
            continue
        key = (len(domain), int(p.get("priority", 0)))
        if key > best_key:
            best_key = key
            best = p
    if best is None:
        return "ALLOW"
    action = str(best.get("action", "ALLOW")).upper()
    return action if action in ("ALLOW", "DENY", "CONFIRM") else "ALLOW"


def sanitize_url(url: str) -> str:
    try:
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
        parts = urlsplit(url)
        q = [(k, "[REDACTED]" if k.lower() in SENSITIVE_KEYS or "token" in k.lower() or "key" in k.lower() else v)
             for k, v in parse_qsl(parts.query, keep_blank_values=True)]
        encoded = urlencode(q).replace("%5BREDACTED%5D", "[REDACTED]")
        return urlunsplit((parts.scheme, parts.netloc, parts.path, encoded, parts.fragment))
    except Exception:
        return url


def redact_text(text: str) -> str:
    if not text:
        return text
    return SENSITIVE_VALUE_RE.sub("[REDACTED]", text)


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for k, v in data.items():
        if k.lower() in SENSITIVE_KEYS or "password" in k.lower() or "secret" in k.lower():
            redacted[k] = "[REDACTED]"
        elif isinstance(v, dict):
            redacted[k] = redact_dict(v)
        elif isinstance(v, str):
            redacted[k] = redact_text(v)
        elif isinstance(v, list):
            redacted[k] = [redact_dict(i) if isinstance(i, dict) else (redact_text(i) if isinstance(i, str) else i) for i in v]
        else:
            redacted[k] = v
    return redacted


def detect_prompt_injection(web_text: str) -> list[str]:
    """Return list of matched injection signals in untrusted web content."""
    hits: list[str] = []
    lowered = web_text.lower()
    for pat in PROMPT_INJECTION_PATTERNS:
        m = re.search(pat, lowered)
        if m:
            hits.append(m.group(0)[:120])
    return hits


def label_untrusted(content: str, limit: int = 8000) -> str:
    body = content[:limit]
    if len(content) > limit:
        body += "... [truncated]"
    return f"[UNTRUSTED_WEB_CONTENT]\n{redact_text(body)}\n[/UNTRUSTED_WEB_CONTENT]"


CHALLENGE_SIGNALS: dict[str, list[str]] = {
    "CAPTCHA": ["captcha", "recaptcha", "hcaptcha", "prove you are human", "select all images"],
    "MFA_REQUIRED": ["two-factor", "2fa", "verification code", "authenticator", "one-time passcode"],
    "LOGIN_REQUIRED": ["sign in to continue", "log in to continue", "login required", "session expired"],
    "SECURITY_CHECK": ["security check", "verify your identity", "unusual traffic", "access denied"],
    "BOT_CHALLENGE": ["are you a robot", "cloudflare", "perimeterx", "datadome", "press & hold"],
}


def detect_challenge(page_text: str, title: str = "") -> Optional[str]:
    blob = f"{title}\n{page_text}".lower()
    for kind, signals in CHALLENGE_SIGNALS.items():
        if any(s in blob for s in signals):
            return kind
    return None


def classify_risk(action_type: str) -> str:
    return ACTION_RISK.get(action_type.upper(), "MEDIUM")


def requires_approval(action_type: str, risk_policy: Optional[dict[str, Any]] = None) -> bool:
    action = action_type.upper()
    if action in APPROVAL_REQUIRED:
        return True
    if risk_policy:
        return classify_risk(action) in set(risk_policy.get("requireApprovalFor", []))
    return classify_risk(action) in ("HIGH", "CRITICAL")


def is_retry_safe(action_type: str) -> bool:
    return action_type.upper() in RETRY_SAFE


def fingerprint_state(url: str, title: str, text: str, elements: list[Any]) -> dict[str, str]:
    def h(s: str) -> str:
        return hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()
    el_sig = "|".join(sorted(f"{e.get('role', '')}:{e.get('name', '')}" if isinstance(e, dict) else str(e) for e in elements))
    return {
        "url": url,
        "title": title,
        "text_hash": h(text or ""),
        "dom_hash": h(f"{url}|{title}|{text[:2000] if text else ''}"),
        "interactive_elements_hash": h(el_sig),
    }


def detect_loop(fingerprints: list[dict[str, str]], threshold: int = 3) -> Optional[dict[str, str]]:
    if len(fingerprints) < threshold:
        return None
    recent = fingerprints[-(threshold * 2):]
    for key, kind in (("url", "url_repetition"), ("dom_hash", "dom_repetition"),
                      ("interactive_elements_hash", "elements_repetition")):
        counts: dict[str, int] = {}
        for fp in recent:
            counts[fp.get(key, "")] = counts.get(fp.get(key, ""), 0) + 1
        for val, count in counts.items():
            if count >= threshold and val:
                return {"type": kind, "details": f"{key} repeated {count}x: {val[:120]}"}
    return None
