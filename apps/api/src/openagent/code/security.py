"""Code agent security: workspace containment, secret scanning, repo-content
trust boundaries, risk classification, execution profiles.

Repository content is UNTRUSTED data. It must never override system,
organization, tool, credential, sandbox, or approval policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# --------------------------------------------------------------------------
# Workspace path containment
# --------------------------------------------------------------------------

FORBIDDEN_PATH_NAMES = {
    ".git",  # direct .git manipulation goes through the git runner only
}

# Absolute locations a workspace may never resolve to, even via symlinks.
FORBIDDEN_ROOTS = ("/etc", "/root", "/proc", "/sys", "/dev")


@dataclass
class PathValidationResult:
    valid: bool
    reason: str = ""
    resolved: Optional[str] = None


def validate_workspace_path(workspace_root: str, rel_path: str,
                            max_size_bytes: int = 2 * 1024 * 1024) -> PathValidationResult:
    """Fail-closed check that a task-relative path stays inside the workspace.

    Rejects absolute paths, ``..`` escapes, symlink escapes, and oversize files.
    """
    rel = (rel_path or "").replace("\\", "/").strip()
    if not rel:
        return PathValidationResult(valid=False, reason="Empty path")
    if len(rel) > 1024:
        return PathValidationResult(valid=False, reason="Path too long")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        return PathValidationResult(valid=False, reason="Absolute paths are not allowed")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return PathValidationResult(valid=False, reason="Path traversal ('..') is not allowed")
    if parts and parts[0] in FORBIDDEN_PATH_NAMES:
        return PathValidationResult(valid=False, reason=f"Direct access to '{parts[0]}' is not allowed")
    if re.search(r"[\x00-\x1f\x7f]", rel):
        return PathValidationResult(valid=False, reason="Path contains control characters")

    root = Path(workspace_root).resolve()
    # Refuse to operate if the workspace root itself is unsafe.
    if str(root) in FORBIDDEN_ROOTS or any(
        str(root) == fr or str(root).startswith(fr + "/") for fr in FORBIDDEN_ROOTS
    ):
        return PathValidationResult(valid=False, reason="Workspace root is not allowed")
    candidate = (root / Path(*parts)).resolve() if parts else root
    try:
        candidate.relative_to(root)
    except ValueError:
        return PathValidationResult(valid=False, reason="Resolved path escapes the workspace")
    if candidate.is_file():
        try:
            if candidate.stat().st_size > max_size_bytes:
                return PathValidationResult(valid=False, reason="File exceeds size limit")
        except OSError:
            return PathValidationResult(valid=False, reason="Cannot stat file")
    return PathValidationResult(valid=True, resolved=str(candidate))


# --------------------------------------------------------------------------
# Secret scanning
# --------------------------------------------------------------------------

SECRET_PATTERNS: list[tuple[str, str]] = [
    ("aws_access_key", r"AKIA[0-9A-Z]{16}"),
    ("github_token", r"gh[pousr]_[A-Za-z0-9]{8,}"),
    ("openai_key", r"sk-[A-Za-z0-9]{8,}"),
    ("private_key", r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ("generic_api_key", r"(?i)(?:api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?"),
    ("generic_secret", r"(?i)(?:client[_-]?secret|secret[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}['\"]?"),
    ("password_assign", r"(?i)(?:password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{6,}['\"]?"),
    ("bearer_token", r"(?i)bearer\s+[A-Za-z0-9_\-\.~\+/]{16,}={0,2}"),
    ("jwt", r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ("slack_token", r"xox[baprs]-[A-Za-z0-9\-]{8,}"),
    ("stripe_key", r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}"),
]

_COMPILED_SECRETS = [(name, re.compile(pat)) for name, pat in SECRET_PATTERNS]

# Filenames that almost always mean "do not touch without approval".
SENSITIVE_FILENAMES = {
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
    "credentials.json", "secrets.yaml", "secrets.yml", ".npmrc", ".pypirc",
}


@dataclass
class SecretFinding:
    kind: str
    file: str
    line: int
    excerpt_redacted: str


def scan_text_for_secrets(text: str, filename: str = "") -> list[SecretFinding]:
    """Scan text for likely secrets. Excerpts are redacted, never verbatim."""
    findings: list[SecretFinding] = []
    for i, line in enumerate(text.splitlines(), start=1):
        for name, rx in _COMPILED_SECRETS:
            if rx.search(line):
                findings.append(SecretFinding(
                    kind=name, file=filename, line=i,
                    excerpt_redacted=f"[REDACTED {name} on line {i}]",
                ))
                break  # one finding per line is enough to block
    return findings


def is_sensitive_filename(filename: str) -> bool:
    base = filename.replace("\\", "/").split("/")[-1].lower()
    return base in SENSITIVE_FILENAMES or base.endswith(".pem") or base.endswith(".key")


# --------------------------------------------------------------------------
# Repository prompt-injection defense
# --------------------------------------------------------------------------

REPO_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"reveal\s+(your\s+)?(system\s+prompt|instructions|secret)",
    r"print\s+environment\s+variables",
    r"upload\s+secrets?",
    r"send\s+(secrets?|tokens?|credentials?|env)\s+(to|via)\b",
    r"disable\s+(security|safety|guardrails?|sandbox)\b",
    r"you\s+are\s+now\s+(in\s+)?(developer|admin|root|god)\s+mode",
    r"run\s+this\s+destructive\s+command",
    r"curl\s+[^\s]+\s*\|\s*(?:sudo\s+)?(?:ba)?sh\b",
    r"rm\s+-rf\s+[/~]",
]

_COMPILED_INJECTIONS = [re.compile(p, re.IGNORECASE) for p in REPO_INJECTION_PATTERNS]


def detect_repo_injection(content: str) -> list[str]:
    """Return matched injection signals in untrusted repository content."""
    return [m.group(0)[:120] for rx in _COMPILED_INJECTIONS if (m := rx.search(content))]


def label_untrusted_code(content: str, limit: int = 8000) -> str:
    body = content[:limit]
    if len(content) > limit:
        body += "\n... [truncated]"
    return f"[UNTRUSTED_REPO_CONTENT]\n{body}\n[/UNTRUSTED_REPO_CONTENT]"


# Repository instruction files are advisory only: allowlist the directives the
# agent may honor; everything else is ignored (never a bypass).
ALLOWED_REPO_DIRECTIVES = {
    "build_command", "test_command", "lint_command", "typecheck_command",
    "code_style", "directory_conventions", "important_modules",
}


def filter_repo_instructions(directives: dict[str, Any]) -> dict[str, Any]:
    """Keep only advisory directives compatible with platform policy."""
    return {k: v for k, v in directives.items() if k in ALLOWED_REPO_DIRECTIVES}


# --------------------------------------------------------------------------
# Risk classification
# --------------------------------------------------------------------------

TOOL_RISK: dict[str, str] = {
    # LOW — read-only
    "code.repository.list": "LOW", "code.repository.status": "LOW",
    "code.file.list": "LOW", "code.file.read": "LOW",
    "code.search": "LOW", "code.symbol.find": "LOW", "code.reference.find": "LOW",
    "code.diff": "LOW", "code.review": "LOW",
    # MEDIUM — workspace mutation, local validation
    "code.patch.apply": "MEDIUM", "code.branch.create": "MEDIUM",
    "code.test.run": "MEDIUM", "code.lint.run": "MEDIUM",
    "code.typecheck.run": "MEDIUM", "code.build.run": "MEDIUM",
    "code.git.fetch": "MEDIUM", "code.git.commit": "MEDIUM",
    "code.pr.prepare": "MEDIUM",
    # HIGH — remote/shared impact
    "code.git.push": "HIGH", "code.dependencies.change": "HIGH",
    "code.migration.run": "HIGH", "code.ci.modify": "HIGH",
    # CRITICAL — destructive / production
    "code.git.force_push": "CRITICAL", "code.branch.delete": "CRITICAL",
    "code.deploy": "CRITICAL", "code.credentials.change": "CRITICAL",
}

APPROVAL_REQUIRED_TOOLS = {
    "code.git.push", "code.git.force_push", "code.branch.delete",
    "code.dependencies.change", "code.migration.run", "code.deploy",
    "code.patch.apply",  # patches to protected paths always confirm
}


def classify_tool_risk(tool_name: str) -> str:
    return TOOL_RISK.get(tool_name, "MEDIUM")


def tool_requires_approval(tool_name: str, risk_policy: Optional[dict[str, Any]] = None) -> bool:
    if tool_name in APPROVAL_REQUIRED_TOOLS:
        # code.patch.apply is approval-gated only for sensitive/protected paths;
        # the service decides per-patch. Other listed tools always require it.
        if tool_name != "code.patch.apply":
            return True
    if risk_policy:
        return classify_tool_risk(tool_name) in set(risk_policy.get("requireApprovalFor", []))
    return classify_tool_risk(tool_name) in ("HIGH", "CRITICAL")


# Retry-safe tools may be re-driven after worker crashes; mutating tools may not.
RETRY_SAFE_TOOLS = {
    "code.repository.list", "code.repository.status", "code.file.list",
    "code.file.read", "code.search", "code.symbol.find", "code.reference.find",
    "code.diff", "code.lint.run", "code.typecheck.run", "code.build.run",
    "code.review",
}


def is_retry_safe_tool(tool_name: str) -> bool:
    return tool_name in RETRY_SAFE_TOOLS


# --------------------------------------------------------------------------
# Execution profiles (MP18 sandbox will enforce; profiles define the contract)
# --------------------------------------------------------------------------

@dataclass
class ExecutionProfile:
    name: str
    allowed_commands: list[str]
    network: str = "none"  # none | restricted | full
    timeout_seconds: int = 600
    max_output_bytes: int = 1_000_000
    cpu_limit: str = "1.0"
    memory_limit: str = "2g"
    allow_write: bool = False


EXECUTION_PROFILES: dict[str, ExecutionProfile] = {
    "TEST": ExecutionProfile(
        name="TEST",
        allowed_commands=["pytest", "python -m pytest", "npm test", "pnpm test",
                          "yarn test", "go test", "cargo test", "dotnet test"],
        timeout_seconds=1200, allow_write=False,
    ),
    "LINT": ExecutionProfile(
        name="LINT",
        allowed_commands=["ruff", "eslint", "flake8", "pylint", "golangci-lint",
                          "clippy", "dotnet format --verify-no-changes"],
        timeout_seconds=600, allow_write=False,
    ),
    "TYPECHECK": ExecutionProfile(
        name="TYPECHECK",
        allowed_commands=["mypy", "tsc", "pyright", "go vet", "cargo check"],
        timeout_seconds=600, allow_write=False,
    ),
    "BUILD": ExecutionProfile(
        name="BUILD",
        allowed_commands=["npm run build", "pnpm build", "tsc", "go build",
                          "cargo build", "dotnet build", "make"],
        timeout_seconds=1200, allow_write=True,
    ),
    "PACKAGE": ExecutionProfile(
        name="PACKAGE",
        allowed_commands=["npm pack", "pip wheel", "cargo package", "go mod tidy"],
        timeout_seconds=900, allow_write=True,
    ),
    "MIGRATION": ExecutionProfile(
        name="MIGRATION",
        allowed_commands=["alembic upgrade", "alembic downgrade", "prisma migrate",
                          "dotnet ef database update"],
        timeout_seconds=600, allow_write=True,
    ),
    "CUSTOM": ExecutionProfile(
        name="CUSTOM", allowed_commands=[], timeout_seconds=300, allow_write=False,
    ),
}


def resolve_profile(name: str) -> ExecutionProfile:
    return EXECUTION_PROFILES.get(name.upper(), EXECUTION_PROFILES["CUSTOM"])


def command_allowed_by_profile(command: str, profile: ExecutionProfile) -> bool:
    """Prefix-match the command against the profile allowlist (no shell parsing)."""
    cmd = command.strip()
    return any(cmd == a or cmd.startswith(a + " ") for a in profile.allowed_commands)


# --------------------------------------------------------------------------
# Branch protection
# --------------------------------------------------------------------------

DEFAULT_PROTECTED_BRANCHES = {"main", "master", "production", "release"}


def is_protected_branch(branch: str, extra_protected: Optional[list[str]] = None) -> bool:
    protected = set(DEFAULT_PROTECTED_BRANCHES) | set(extra_protected or [])
    return branch in protected or any(
        p.endswith("*") and branch.startswith(p[:-1]) for p in protected
    )


def task_branch_name(task_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", task_id)[:48]
    return f"openagent/task/{safe}"


def redact_text(text: str) -> str:
    """Redact likely secret material before logs/model context."""
    if not text:
        return text
    out = text
    for _name, rx in _COMPILED_SECRETS:
        out = rx.sub("[REDACTED]", out)
    # URL-embedded credentials (https://user:token@host/...) — scheme kept.
    out = re.sub(r"(?<=://)[^/\s@]+@", "[REDACTED]@", out)
    return out


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for k, v in data.items():
        kl = k.lower()
        if kl in {"password", "passwd", "secret", "token", "private_key",
                  "client_secret", "api_key", "apikey", "credential", "auth"}:
            redacted[k] = "[REDACTED]"
        elif isinstance(v, dict):
            redacted[k] = redact_dict(v)
        elif isinstance(v, str):
            redacted[k] = redact_text(v)
        elif isinstance(v, list):
            redacted[k] = [redact_dict(i) if isinstance(i, dict)
                           else (redact_text(i) if isinstance(i, str) else i) for i in v]
        else:
            redacted[k] = v
    return redacted
