"""MP27: DLP hook + secret detection (§53-55). High-confidence
patterns only (no false-positive-heavy universal DLP). Redact before
logs, telemetry, artifacts, and model context."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# High-confidence secret shapes.
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "openai_key": re.compile(r"sk-(live|test|proj)-[A-Za-z0-9]{8,}"),
    "github_token": re.compile(r"(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}"),
    "private_key": re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "db_url": re.compile(
        r"(postgres|mysql|mongodb)(\+\w+)?://[^/\s]*:[^/\s]*@[^/\s]+",
        re.IGNORECASE),
    "bearer": re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{12,}"),
    "generic_password": re.compile(
        r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?([^'\"\\s]{4,})"),
}

SECRET_VALUE_KEY_HINTS = ("password", "secret", "token", "api_key",
                          "private_key", "credential", "passwd", "pwd")


def find_secrets(text: str) -> list[dict[str, str]]:
    findings = []
    for name, pattern in SECRET_PATTERNS.items():
        try:
            for match in pattern.finditer(text or ""):
                findings.append({"type": name,
                                 "span": f"{match.start()}:{match.end()}"})
        except re.error:
            continue
    return findings


def redact_text(text: str) -> str:
    out = text or ""
    for pattern in SECRET_PATTERNS.values():
        try:
            out = pattern.sub("[REDACTED]", out)
        except re.error:
            continue
    return out


@dataclass
class DataRule:
    rule_id: str
    classification: str  # PUBLIC..SECRET (identity.types)
    pattern: str = ""    # regex or "" for key-hint rules
    action: str = "redact"  # redact|block|allow

    def validate(self) -> tuple[bool, str]:
        from openagent.identity.types import DataClassification
        if self.classification not in DataClassification.ALL:
            return False, f"unknown classification {self.classification}"
        if self.action not in ("redact", "block", "allow"):
            return False, f"unknown action {self.action}"
        if self.pattern:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                return False, f"invalid pattern: {exc}"
        return True, "ok"


class DataPolicyEngine:
    """inspect/classify/redact/allow over explicit rules + built-ins."""

    def __init__(self, rules: list[DataRule] | None = None) -> None:
        self._rules = list(rules or [])

    def add(self, rule: DataRule) -> None:
        ok, reason = rule.validate()
        if not ok:
            raise ValueError(reason)
        self._rules.append(rule)

    def inspect(self, text: str) -> dict[str, Any]:
        builtin = find_secrets(text)
        rule_hits = []
        for rule in self._rules:
            if rule.pattern and re.search(rule.pattern, text or ""):
                rule_hits.append(rule.rule_id)
        return {"secret_findings": builtin, "rule_hits": rule_hits,
                "sensitive": bool(builtin or rule_hits)}

    def classify(self, text: str, requested: str = "") -> str:
        from openagent.identity.types import DataClassification
        if requested in DataClassification.ALL:
            return requested
        if find_secrets(text):
            return DataClassification.SECRET
        lowered = (text or "").lower()
        if any(w in lowered for w in ("ssn", "biometric",
                                      "health record")):
            return DataClassification.RESTRICTED
        if any(w in lowered for w in SECRET_VALUE_KEY_HINTS):
            return DataClassification.CONFIDENTIAL
        return DataClassification.INTERNAL

    def redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: ("[REDACTED]"
                        if str(k).lower() in SECRET_VALUE_KEY_HINTS
                        and isinstance(v, str)
                        else self.redact(v))
                    for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redact(v) for v in value]
        if isinstance(value, str):
            return redact_text(value)
        return value

    def allow(self, text: str) -> tuple[bool, str]:
        for rule in self._rules:
            if rule.action == "block" and rule.pattern and \
                    re.search(rule.pattern, text or ""):
                return False, f"blocked by rule {rule.rule_id}"
        return True, "allowed"
