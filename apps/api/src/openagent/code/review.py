"""Structured code review: static findings with severity, file, line, evidence.

Heuristic analyzers catch common defect/security/style classes deterministically.
Model-based deep review plugs in through the agent runtime (reviewer agent);
this module defines the finding schema, aggregation, and gating used by both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from openagent.code.security import scan_text_for_secrets

SEVERITIES = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")
CATEGORIES = {"correctness", "security", "performance", "maintainability",
              "tests", "api", "errors", "style", "secrets"}


@dataclass
class ReviewFinding:
    severity: str
    file: str
    line: int
    category: str
    finding: str
    evidence: str = ""  # short excerpt (already secret-scanned by callers)
    suggested_fix: str = ""


@dataclass
class ReviewResult:
    findings: list[ReviewFinding] = field(default_factory=list)
    summary: str = ""
    passed: bool = True  # False when HIGH/CRITICAL findings exist

    def add(self, finding: ReviewFinding) -> None:
        self.findings.append(finding)
        if finding.severity in ("HIGH", "CRITICAL"):
            self.passed = False


# pattern, severity, category, message, suggested fix
RULES: list[tuple[str, str, str, str, str]] = [
    (r"\beval\s*\(", "HIGH", "security",
     "Use of eval() enables arbitrary code execution.",
     "Replace with explicit parsing or an allowlisted dispatch table."),
    (r"\bexec\s*\(", "HIGH", "security",
     "Use of exec() enables arbitrary code execution.",
     "Refactor into explicit functions; never exec() untrusted input."),
    (r"os\.system\s*\(", "HIGH", "security",
     "os.system() invokes a shell and risks command injection.",
     "Use subprocess with argument lists (no shell) inside the execution boundary."),
    (r"subprocess\.(?:call|run|Popen)\s*\([^)]*shell\s*=\s*True", "HIGH", "security",
     "shell=True enables command injection.",
     "Pass argv lists with shell=False through the approved execution boundary."),
    (r"pickle\.loads?\s*\(", "MEDIUM", "security",
     "Pickle deserialization of untrusted data is unsafe.",
     "Use JSON or another safe serialization format."),
    (r"yaml\.load\s*\([^)]*Loader\s*=\s*yaml\.Loader", "MEDIUM", "security",
     "Unsafe YAML loading can execute arbitrary objects.",
     "Use yaml.safe_load()."),
    (r"password\s*=\s*['\"][^'\"]+['\"]", "CRITICAL", "secrets",
     "Hardcoded password detected.", "Move to the credential system; reference by credential_ref."),
    (r"except\s*:\s*(?:pass)?\s*$", "MEDIUM", "errors",
     "Bare except swallows errors (and possibly control flow).",
     "Catch specific exceptions and log them."),
    (r"except\s+Exception\s*:\s*pass", "MEDIUM", "errors",
     "Silent exception swallowing hides failures.",
     "Log the error or re-raise with context."),
    (r"#\s*TODO\b", "INFO", "maintainability",
     "TODO marker left in code.", "Resolve or file a tracked task."),
    (r"#\s*FIXME\b", "LOW", "maintainability",
     "FIXME marker left in code.", "Fix before merging or track explicitly."),
    (r"console\.log\s*\(", "INFO", "maintainability",
     "console.log in shipped code.", "Use the structured logger."),
    (r"print\s*\(", "INFO", "maintainability",
     "print() in library code.", "Use the structured logger."),
    (r"SELECT\s+.*\+\s*", "MEDIUM", "security",
     "Possible SQL string concatenation.", "Use parameterized queries."),
    (r"\.innerHTML\s*=", "MEDIUM", "security",
     "innerHTML assignment risks XSS.", "Use textContent or sanitized templating."),
    (r"dangerouslySetInnerHTML", "MEDIUM", "security",
     "Raw HTML injection risks XSS.", "Sanitize or avoid."),
    (r"setTimeout\s*\(\s*['\"]", "MEDIUM", "security",
     "String argument to setTimeout is eval-like.", "Pass a function reference."),
]


def _compiled_rules() -> list[tuple[re.Pattern[str], str, str, str, str]]:
    return [(re.compile(pat), sev, cat, msg, fix) for pat, sev, cat, msg, fix in RULES]


def review_text(content: str, filename: str,
                max_findings: int = 100) -> ReviewResult:
    """Run static analyzers + secret scan over file content."""
    result = ReviewResult()
    for secret in scan_text_for_secrets(content, filename):
        result.add(ReviewFinding(
            severity="CRITICAL", file=secret.file, line=secret.line,
            category="secrets",
            finding=f"Likely secret material ({secret.kind}).",
            evidence=secret.excerpt_redacted,
            suggested_fix="Remove the secret; use the credential system (credential_ref)."))
    for rx, severity, category, message, fix in _compiled_rules():
        for m in rx.finditer(content):
            lineno = content.count("\n", 0, m.start()) + 1
            line = content.splitlines()[lineno - 1].strip()[:200]
            result.add(ReviewFinding(
                severity=severity, file=filename, line=lineno, category=category,
                finding=message, evidence=line, suggested_fix=fix))
            if len(result.findings) >= max_findings:
                break
        if len(result.findings) >= max_findings:
            break
    result.summary = (f"{len(result.findings)} finding(s); "
                      f"{'BLOCKED' if not result.passed else 'no blocking issues'}")
    return result


def review_diff(diff_text: str, max_findings: int = 200) -> ReviewResult:
    """Review only added lines of a unified diff (pre-commit/PR path)."""
    result = ReviewResult()
    current_file = ""
    lineno = 0
    buffer: dict[str, list[tuple[int, str]]] = {}
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            current_file = raw[4:].strip()
            if current_file.startswith("b/"):
                current_file = current_file[2:]
            lineno = 0
        elif raw.startswith("@@"):
            m = re.match(r"^\@\@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? \@\@", raw)
            lineno = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            buffer.setdefault(current_file, []).append((lineno, raw[1:]))
            lineno += 1
        elif raw.startswith(" "):
            lineno += 1
        elif raw.startswith("-"):
            pass
    for filename, lines in buffer.items():
        joined = "\n".join(text for _, text in lines)
        sub = review_text(joined, filename or "unknown",
                          max_findings=max(0, max_findings - len(result.findings)))
        # Map back to approximate diff line numbers.
        offset = 0
        for f in sub.findings:
            if 1 <= f.line <= len(lines):
                f.line = lines[f.line - 1][0]
            result.add(f)
            offset += 1
            if len(result.findings) >= max_findings:
                break
    result.summary = (f"{len(result.findings)} finding(s) in changed lines; "
                      f"{'BLOCKED' if not result.passed else 'no blocking issues'}")
    return result


def gate_summary(result: ReviewResult) -> dict[str, Any]:
    by_sev: dict[str, int] = {}
    for f in result.findings:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    return {"passed": result.passed, "summary": result.summary,
            "by_severity": by_sev,
            "blocking": [f.__dict__ for f in result.findings
                         if f.severity in ("HIGH", "CRITICAL")][:20]}
