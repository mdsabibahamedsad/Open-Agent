"""MP28: static security analysis + secret detection (§32-33, §87).

Defense layer (not a replacement for review): scans extension source for
hard-coded secrets, unsafe execution, injection, traversal, SSRF, eval,
credential logging, and unsafe install hooks. Publishing fails on
high-confidence secrets unless an explicit, audited false-positive
override is supplied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# -- high-confidence secret patterns (block publishing) ----------------------

SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    ("aws-access-key", r"AKIA[0-9A-Z]{16}"),
    ("aws-secret", r"aws_secret_access_key\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    ("private-key", r"-----BEGIN (?:RSA )?PRIVATE KEY-----"),
    ("openai-key", r"sk-[A-Za-z0-9]{20,}"),
    ("github-token", r"gh[pousr]_[A-Za-z0-9]{20,}"),
    ("generic-api-key", r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
    ("password-assign", r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"][^'\"]{4,}['\"]"),
    ("bearer-token", r"(?i)bearer\s+[A-Za-z0-9\-._~+/]{20,}"),
    ("oauth-secret", r"(?i)(client_secret|oauth_secret)\s*[:=]\s*['\"][^'\"]{6,}['\"]"),
    ("connection-string", r"(?i)(postgres|mysql|mongodb)(://|:)[^\\s'\"]+:[^\\s'\"]+@"),
    ("session-token", r"(?i)(session[_-]?token|sessionid)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
)

# -- dangerous code patterns (warn / fail by severity) ------------------------

CODE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # (finding, regex, severity)
    ("unsafe-eval", r"\beval\s*\(", "high"),
    ("dynamic-exec", r"\bexec\s*\(", "high"),
    ("child-process", r"child_process|spawn\s*\(|execSync|execFile", "medium"),
    ("shell-exec-python", r"os\.system\s*\(|subprocess\.(call|run|Popen)\s*\([^)]*shell\s*=\s*True", "high"),
    ("subprocess", r"subprocess\.", "medium"),
    ("path-traversal", r"\.\./\.\.|~\/|\/etc\/passwd", "medium"),
    ("ssrf-risk", r"http\.request|fetch\s*\(\s*(?!['\"]https?://[A-Z_{])[^)]*\+", "medium"),
    ("insecure-redirect", r"followRedirects?\s*[:=]\s*true|allowRedirects", "low"),
    ("credential-logging", r"console\.(log|debug|info)\s*\([^)]*(password|secret|token|api[_-]?key)", "high"),
    ("docker-socket", r"docker\.sock|/var/run/docker", "critical"),
    ("host-filesystem", r"/etc/passwd|/etc/shadow|/proc/self|C:\\\\Windows\\\\System32", "high"),
    ("install-hook-exec", r"\"(preinstall|postinstall|install)\"\s*:", "medium"),
    ("unrestricted-network", r"0\.0\.0\.0|::/0|allowAllHosts|rejectUnauthorized\s*:\s*false", "high"),
    ("disable-tls", r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0|ssl:\s*false|verify:\s*false", "high"),
    ("pickle-loads", r"pickle\.loads?\s*\(", "high"),
    ("yaml-unsafe-load", r"yaml\.load\s*\([^)]*Loader\s*!=\s*safe", "medium"),
)

ALLOWLIST_FILES = ("README", "CHANGELOG", "LICENSE", ".example", "example", "test", "mock", "fixture")


@dataclass
class Finding:
    rule: str
    severity: str  # low|medium|high|critical
    file: str
    line: int
    excerpt: str
    message: str


@dataclass
class ScanReport:
    findings: list[Finding] = field(default_factory=list)
    secret_hits: list[Finding] = field(default_factory=list)

    @property
    def blocks_publish(self) -> bool:
        if self.secret_hits:
            return True
        return any(f.severity == "critical" for f in self.findings)

    @property
    def blocks_install(self) -> bool:
        return any(f.severity == "critical" for f in self.findings)

    def to_dict(self) -> dict:
        return {
            "blocks_publish": self.blocks_publish,
            "blocks_install": self.blocks_install,
            "secret_hits": [f.__dict__ for f in self.secret_hits],
            "findings": [f.__dict__ for f in self.findings],
        }


def _is_allowlisted(path: str) -> bool:
    lowered = path.lower()
    return any(token in lowered for token in ("readme", "changelog", "license", ".example", "fixture", "mock"))


def scan_files(files: dict[str, str]) -> ScanReport:
    """Scan a mapping of relative-path -> text content."""
    report = ScanReport()
    for path, content in files.items():
        lines = content.splitlines() or [""]
        for idx, line in enumerate(lines, start=1):
            excerpt = line.strip()[:160]
            for rule, pattern in SECRET_PATTERNS:
                try:
                    if re.search(pattern, line):
                        if _is_allowlisted(path) and "example" in line.lower():
                            continue
                        report.secret_hits.append(Finding(
                            rule=f"secret:{rule}", severity="critical",
                            file=path, line=idx, excerpt=excerpt,
                            message=f"Possible hard-coded secret ({rule}). "
                            "Remove it; use a secret reference instead.",
                        ))
                except re.error:
                    continue
            for rule, pattern, severity in CODE_PATTERNS:
                try:
                    if re.search(pattern, line):
                        report.findings.append(Finding(
                            rule=rule, severity=severity, file=path,
                            line=idx, excerpt=excerpt,
                            message=f"Suspicious pattern '{rule}' — review required.",
                        ))
                except re.error:
                    continue
    return report


# Install-hook policy (§87): package installation must never auto-execute
# host-privileged scripts. Hooks are metadata only; any build runs inside
# the sandbox boundary and is verified before install.
BLOCKED_INSTALL_HOOKS = ("preinstall", "install", "postinstall")


def install_hooks_safe(package_json: dict) -> list[str]:
    scripts = package_json.get("scripts", {}) if isinstance(package_json, dict) else {}
    return [h for h in BLOCKED_INSTALL_HOOKS if h in scripts]
