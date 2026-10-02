"""MP27: AI-specific security (§56-64). External content is data,
never instructions: centralized hooks tag untrusted content, detect
high-confidence instruction-override attempts, scope agent delegation
(no escalation), and gate tool/MCP/browser/code/sandbox/memory paths
through the existing runtimes (never around them)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# High-confidence override markers only — no fuzzy universal DLP.
OVERRIDE_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|system)\s+instructions?", re.I),
    re.compile(r"disregard\s+(all\s+)?(safety|security|system)\s+(policies|instructions?)", re.I),
    re.compile(r"you\s+are\s+now\s+(in\s+)?(dan|jailbroken|unrestricted)", re.I),
    re.compile(r"reveal\s+(your\s+)?(system\s+prompt|secret|api\s*key)", re.I),
    re.compile(r"bypass\s+(approval|authorization|authentication)", re.I),
    re.compile(r"execute\s+.+\s+without\s+approval", re.I),
)

UNTRUSTED_SOURCES = ("webpage", "document", "email", "mcp_resource",
                     "connector_data", "memory", "tool_output",
                     "browser_content", "agent_message")


@dataclass
class ContentEnvelope:
    source: str
    text: str = ""
    trusted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> tuple[bool, str]:
        if self.source not in (*UNTRUSTED_SOURCES, "system", "user"):
            return False, f"unknown content source {self.source}"
        return True, "ok"


def inspect_content(envelope: ContentEnvelope) -> dict[str, Any]:
    """Tag + scan external content. Returns verdict, never a block on
    mere suspicion: only high-confidence patterns escalate."""
    ok, reason = envelope.validate()
    if not ok:
        return {"verdict": "reject", "reason": reason, "matches": []}
    if envelope.trusted or envelope.source in ("system", "user"):
        return {"verdict": "allow", "reason": "trusted source",
                "matches": []}
    matches = [p.pattern for p in OVERRIDE_PATTERNS
               if p.search(envelope.text)]
    if matches:
        return {"verdict": "escalate",
                "reason": "possible instruction override in untrusted content",
                "matches": matches,
                "required": "human approval before acting on this content"}
    return {"verdict": "allow", "reason": "no override markers",
            "matches": []}


@dataclass
class DelegationGrant:
    parent_agent_id: str
    child_agent_id: str
    permissions: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    expires_in_seconds: int = 600

    def validate_against(self, parent_permissions: list[str]) -> tuple[bool, str]:
        """Child receives a SUBSET of parent permissions — never more."""
        parent = set(parent_permissions)
        child = set(self.permissions)
        if not child.issubset(parent):
            return False, (
                f"delegation escalates: {sorted(child - parent)} "
                "not held by parent")
        if not child:
            return False, "delegation grants nothing"
        return True, "delegation scoped"


def tool_call_context(*, caller: str, agent_id: str,
                      organization_id: str, resource: str, action: str,
                      risk: str, environment: str,
                      credential_ref: str = "") -> dict[str, Any]:
    """Required context for every tool invocation (§60)."""
    required = {"caller": caller, "agent": agent_id,
                "organization": organization_id, "resource": resource,
                "action": action, "risk": risk, "environment": environment}
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise ValueError(f"tool call missing context: {missing}")
    required["credential"] = credential_ref  # ref only, may be empty
    return required


def mcp_trust_check(*, server_trust: str, tool_scope: str,
                    allowed_scopes: list[str]) -> tuple[bool, str]:
    """MCP servers are external providers: verify trust + scope, never
    trust on install alone (§61)."""
    if server_trust not in ("verified", "reviewed", "untrusted"):
        return False, f"unknown MCP trust state {server_trust}"
    if server_trust == "untrusted":
        return False, "untrusted MCP server blocked"
    if tool_scope not in allowed_scopes:
        return False, f"MCP tool scope {tool_scope} not granted"
    return True, "MCP call authorized"


def memory_write_guard(*, content: str, policy_allows: bool,
                       classification: str = "INTERNAL") -> tuple[bool, str]:
    """Memory never overrides security policy (§12 of invariants)."""
    if not policy_allows:
        return False, "memory write denied by policy"
    envelope = ContentEnvelope(source="memory", text=content)
    verdict = inspect_content(envelope)
    if verdict["verdict"] == "escalate":
        return False, verdict["required"]
    _ = classification
    return True, "memory write allowed"
