"""MP22: package security scanner + trust policy.

Treats package contents as **untrusted data**. Scans manifests, resource
payloads and skill instructions for:

- unrestricted shell / host filesystem / docker socket access
- privileged containers, unrestricted network, unsafe HTTP endpoints
- dangerous connector scopes, destructive tools, missing approvals
- unsafe browser / sandbox configuration
- prompt-injection and credential-exfiltration patterns
- cross-tenant references
- raw embedded secrets (via :mod:`openagent.packages.config_schema`)

Findings use ``{code, path, severity, message}``. Trust levels tune how
loud the installer must be — they never grant permissions.
"""

from __future__ import annotations

import re
from typing import Any

from openagent.packages.config_schema import find_secret_values
from openagent.packages.types import Severity, TrustLevel

# -- pattern tables -----------------------------------------------------------

_SHELL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("SHELL_EXEC", re.compile(r"(?i)\b(os\.system|subprocess|shell\s*=\s*true|exec\s*\()")),
    ("HOST_FS", re.compile(r"(?i)(/etc/passwd|/proc/self|/var/run/docker\.sock|hostPath|/root/)")),
    ("DOCKER_SOCKET", re.compile(r"docker\.sock")),
    ("PRIVILEGED", re.compile(r"(?i)privileged\s*[:=]\s*true")),
    ("UNRESTRICTED_NET", re.compile(r"(?i)network\s*[:=]\s*['\"]?host['\"]?")),
    ("CURL_PIPE", re.compile(r"curl[^|\n]*\|\s*(sh|bash)")),
    ("RM_RF", re.compile(r"rm\s+-rf\s+/( |$|\*)")),
    ("DROP_TABLE", re.compile(r"(?i)\bdrop\s+(table|database)\b")),
    ("DELETE_WITHOUT_WHERE", re.compile(r"(?i)\bdelete\s+from\s+\w+\s*(;|$)")),
)

_URL_RE = re.compile(r"https?://([A-Za-z0-9.-]+)(?::\d+)?(/[^\s\"']*)?")
_UNSAFE_URL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254"})
_UNSAFE_URL_PATHS = ("/admin", "/.env", "/etc/", "/proc/")

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PROMPT_INJECTION", re.compile(r"(?i)(ignore (all )?previous instructions|disregard (all )?(prior|previous|system) instructions|you are now (in |unrestricted|jailbroken)|do not follow (your|system) (rules|policy|policies))")),
    ("POLICY_OVERRIDE", re.compile(r"(?i)(bypass (approval|policy|rbac|guardrail)|disable (safety|guardrail|approval|sandbox)|run without approval|override (system|security) policy)")),
    ("EXFILTRATION", re.compile(r"(?i)(send\W.*(api[_-]?key|passwd|password|secret|token)\W.*\bto\b|post\W.*credentials?\W.*\bto\b\W.*https?://|exfiltrat)")),
    ("CROSS_TENANT", re.compile(r"(?i)(other tenant|another organization'?s (data|memory|credentials)|cross-tenant)")),
)

_DANGEROUS_SCOPES = frozenset(
    {
        "admin",
        "root",
        "superuser",
        "write:all",
        "*",
        "payment:write",
        "user:impersonate",
        "org:admin",
    }
)

_DESTRUCTIVE_TOOLS = frozenset(
    {
        "shell.exec",
        "shell.run",
        "filesystem.delete",
        "filesystem.write",
        "database.drop",
        "database.delete",
        "container.privileged",
        "network.open",
    }
)

_HIGH_RISK_ACTIONS = frozenset(
    {
        "send_email",
        "delete_data",
        "publish_content",
        "modify_production",
        "execute_external_payment",
        "merge_code",
    }
)

_APPROVAL_DECLARATION_KEYS = ("required_approvals", "approvals", "approval_required")


def _finding(code: str, path: str, severity: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "severity": severity, "message": message}


def scan_text_blob(text: str, path: str) -> list[dict[str, str]]:
    """Scan a free-text blob (instructions, prompts, descriptions)."""
    findings: list[dict[str, str]] = []
    if not isinstance(text, str) or not text:
        return findings
    for code, pattern in (*_SHELL_PATTERNS, *_INJECTION_PATTERNS):
        if pattern.search(text):
            severity = (
                Severity.BLOCKER.value
                if code in ("PROMPT_INJECTION", "POLICY_OVERRIDE", "EXFILTRATION",
                            "CROSS_TENANT", "SECRET_LEAK")
                else Severity.ERROR.value
            )
            findings.append(
                _finding(
                    code,
                    path,
                    severity,
                    f"{code}: suspicious pattern in {path}",
                )
            )
    for match in _URL_RE.finditer(text):
        host = match.group(1).lower()
        url_path = match.group(2) or ""
        if host in _UNSAFE_URL_HOSTS:
            findings.append(
                _finding(
                    "UNSAFE_ENDPOINT",
                    path,
                    Severity.ERROR.value,
                    f"UNSAFE_ENDPOINT: internal/metadata URL {match.group(0)!r} in {path}",
                )
            )
        if any(url_path.startswith(prefix) for prefix in _UNSAFE_URL_PATHS):
            findings.append(
                _finding(
                    "UNSAFE_ENDPOINT",
                    path,
                    Severity.WARNING.value,
                    f"UNSAFE_ENDPOINT: sensitive path {match.group(0)!r} in {path}",
                )
            )
    return findings


def scan_manifest_dict(manifest: dict[str, Any]) -> list[dict[str, str]]:
    """Run the full static security scan over a raw manifest dict."""
    findings: list[dict[str, str]] = []
    # 1. Raw secrets anywhere in the bundle.
    for hit in find_secret_values(manifest):
        findings.append(
            _finding("SECRET_LEAK", hit["path"], Severity.BLOCKER.value,
                     f"SECRET_LEAK: {hit['reason']} at {hit['path']}")
        )
    # 2. Free-text fields.
    for dotted in ("description", "changelog"):
        findings.extend(scan_text_blob(str(manifest.get(dotted, "") or ""), dotted))
    # 3. Dependencies: suspicious MCP servers / dangerous connector scopes.
    for index, dep in enumerate(manifest.get("dependencies", []) or []):
        if not isinstance(dep, dict):
            continue
        base = f"dependencies[{index}]"
        dtype = str(dep.get("type", "")).lower()
        package = str(dep.get("package", ""))
        if dtype == "mcp" and ("http" in package or package.startswith("http")):
            findings.append(
                _finding("SUSPICIOUS_MCP", base, Severity.WARNING.value,
                         f"SUSPICIOUS_MCP: remote MCP server {package!r} must be allow-listed")
            )
        scope = str(dep.get("scope", ""))
        if scope in _DANGEROUS_SCOPES:
            findings.append(
                _finding("DANGEROUS_SCOPE", base, Severity.ERROR.value,
                         f"DANGEROUS_SCOPE: dependency {package!r} requests scope {scope!r}")
            )
    # 4. Resources: tools, connectors, browser, sandbox, prompts.
    for index, resource in enumerate(manifest.get("resources", []) or []):
        if not isinstance(resource, dict):
            continue
        base = f"resources[{index}]"
        payload = resource.get("payload", {}) if isinstance(resource.get("payload"), dict) else {}
        if isinstance(payload.get("tool"), str) and payload["tool"] in _DESTRUCTIVE_TOOLS:
            findings.append(
                _finding("DESTRUCTIVE_TOOL", base, Severity.ERROR.value,
                         f"DESTRUCTIVE_TOOL: {payload['tool']!r} requires explicit approval")
            )
        for key in _APPROVAL_DECLARATION_KEYS:
            if key in payload and not payload[key]:
                findings.append(
                    _finding("MISSING_APPROVAL", base, Severity.WARNING.value,
                             f"MISSING_APPROVAL: high-risk resource at {base} declares no approvals")
                )
                break
        browser = payload.get("browser", {}) if isinstance(payload.get("browser"), dict) else {}
        if browser.get("unrestricted") is True or browser.get("allow_all_domains") is True:
            findings.append(
                _finding("UNSAFE_BROWSER", base, Severity.ERROR.value,
                         f"UNSAFE_BROWSER: unrestricted browsing declared at {base}")
            )
        sandbox = payload.get("sandbox", {}) if isinstance(payload.get("sandbox"), dict) else {}
        if str(sandbox.get("profile", "")).lower() in ("privileged", "host", "none"):
            findings.append(
                _finding("UNSAFE_SANDBOX", base, Severity.ERROR.value,
                         f"UNSAFE_SANDBOX: unsafe sandbox profile at {base}")
            )
        limits = payload.get("resource_limits", {}) if isinstance(payload.get("resource_limits"), dict) else {}
        if isinstance(limits.get("memory_mb"), int) and limits["memory_mb"] > 16384:
            findings.append(
                _finding("EXCESSIVE_LIMITS", base, Severity.WARNING.value,
                         f"EXCESSIVE_LIMITS: memory limit {limits['memory_mb']}MB at {base}")
            )
        # Scan embedded instructions/prompts as untrusted content.
        for text_key in ("instructions", "system_prompt", "prompt", "description"):
            if isinstance(payload.get(text_key), str):
                findings.extend(scan_text_blob(payload[text_key], f"{base}.payload.{text_key}"))
    # 5. High-risk actions without approval declarations.
    security = manifest.get("security", {}) if isinstance(manifest.get("security"), dict) else {}
    declared = {str(a).lower() for a in security.get("required_approvals", []) or []}
    mentioned = set()
    blob = str(manifest)
    for action in _HIGH_RISK_ACTIONS:
        if action in blob.lower():
            mentioned.add(action)
    for action in mentioned - declared:
        findings.append(
            _finding("MISSING_APPROVAL", "security.required_approvals",
                     Severity.WARNING.value,
                     f"MISSING_APPROVAL: action {action!r} referenced but no approval declared")
        )
    return findings


def risk_level(findings: list[dict[str, str]]) -> str:
    """Aggregate findings into LOW / MEDIUM / HIGH / CRITICAL."""
    severities = {item.get("severity") for item in findings}
    if Severity.BLOCKER.value in severities:
        return "CRITICAL"
    if Severity.ERROR.value in severities:
        return "HIGH"
    if Severity.WARNING.value in severities:
        return "MEDIUM"
    return "LOW"


def trust_policy(trust: str) -> dict[str, Any]:
    """Execution/installation strictness derived from trust level."""
    trust = str(trust or TrustLevel.UNTRUSTED.value).upper()
    if trust == TrustLevel.CORE.value:
        return {"require_signature": True, "auto_approve_low_risk": True,
                "network": "standard", "sandbox": "standard", "warn_on_install": False}
    if trust == TrustLevel.VERIFIED.value:
        return {"require_signature": True, "auto_approve_low_risk": True,
                "network": "standard", "sandbox": "standard", "warn_on_install": False}
    if trust == TrustLevel.ORGANIZATION.value:
        return {"require_signature": False, "auto_approve_low_risk": True,
                "network": "restricted", "sandbox": "required", "warn_on_install": False}
    if trust == TrustLevel.COMMUNITY.value:
        return {"require_signature": False, "auto_approve_low_risk": False,
                "network": "restricted", "sandbox": "required", "warn_on_install": True}
    return {"require_signature": False, "auto_approve_low_risk": False,
            "network": "denied-by-default", "sandbox": "required",
            "warn_on_install": True}
