"""Structured handoff protocol: package, lifecycle, context policy, artifacts.

Primary mechanism for transferring responsibility between agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openagent.management.types import ContextManifestData, ContextTransferRule, HandoffMode
from openagent.orchestration.security import cap_output, sanitize_dict


@dataclass
class HandoffArtifact:
    kind: str  # file | document | code | dataset | image | report | json | url | db_reference
    name: str
    reference: str  # artifact reference — never inline large binaries
    size_bytes: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StructuredHandoff:
    source_agent_id: Optional[str]
    target_agent_id: Optional[str]
    task_id: str
    objective: str
    completed_work: Dict[str, Any] = field(default_factory=dict)
    pending_work: Dict[str, Any] = field(default_factory=dict)
    decisions: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    artifacts: List[HandoffArtifact] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    known_failures: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    next_action: str = ""
    mode: HandoffMode = HandoffMode.FULL_HANDOFF
    context_rule: ContextTransferRule = ContextTransferRule.TASK_ONLY
    relevant_context: Dict[str, Any] = field(default_factory=dict)


# Classification of context keys to transfer rules. Unknown keys default to
# TASK_ONLY when task-scoped, otherwise excluded.
def classify_context(
    context: Dict[str, Any],
    rule: ContextTransferRule,
    *,
    task_keys: Optional[set[str]] = None,
    team_keys: Optional[set[str]] = None,
) -> tuple[Dict[str, Any], ContextManifestData]:
    """Apply transfer policy: inspect classification, enforce permissions
    (caller-provided key sets), remove secrets, enforce size limits, and
    build an auditable manifest."""
    task_keys = task_keys or set()
    team_keys = team_keys or set()
    included: Dict[str, Any] = {}
    excluded: List[str] = []
    redacted: List[str] = []
    manifest = ContextManifestData(policy=rule.value)

    for key, value in context.items():
        if rule == ContextTransferRule.PRIVATE:
            excluded.append(key)
            continue
        if rule == ContextTransferRule.PUBLIC:
            allowed = True
        elif rule == ContextTransferRule.TASK_ONLY:
            allowed = key in task_keys
        elif rule == ContextTransferRule.TEAM_ONLY:
            allowed = key in team_keys
        elif rule in (ContextTransferRule.AUTHORIZED_SHARED, ContextTransferRule.REDACTED):
            allowed = key in task_keys or key in team_keys
        else:
            allowed = False
        if not allowed:
            excluded.append(key)
            continue
        cleaned = sanitize_dict({key: value})
        if cleaned.get(key) == "[REDACTED]" or (
            isinstance(value, dict) and any(v == "[REDACTED]" for v in cleaned.get(key, {}).values())
        ):
            redacted.append(key)
        included[key] = cleaned[key]

    # Size limits: cap total transfer at 256KB, prefer references.
    capped = cap_output(included, 256 * 1024)
    if capped.get("_truncated"):
        excluded.append("_truncated_overflow")
    manifest.included_items = sorted(included.keys())
    manifest.excluded_items = sorted(excluded)
    manifest.redacted_items = sorted(redacted)
    return capped, manifest


def build_structured_handoff(
    handoff: StructuredHandoff,
    *,
    task_keys: Optional[set[str]] = None,
    team_keys: Optional[set[str]] = None,
) -> Dict[str, Any]:
    """Validate + sanitize a handoff into a persistable package dict."""
    if handoff.mode == HandoffMode.FULL_HANDOFF and not handoff.next_action:
        raise ValueError("full handoff requires next_action")
    transferred, manifest = classify_context(
        dict(handoff.relevant_context or {}),
        handoff.context_rule,
        task_keys=task_keys,
        team_keys=team_keys,
    )
    manifest.source = handoff.source_agent_id or ""
    manifest.target = handoff.target_agent_id or ""
    artifacts = [
        {
            "kind": a.kind,
            "name": a.name,
            "reference": a.reference,  # references only, never binary blobs
            "size_bytes": a.size_bytes,
            "metadata": sanitize_dict(dict(a.metadata)),
        }
        for a in handoff.artifacts
    ]
    total_artifact_bytes = sum(a.size_bytes for a in handoff.artifacts)
    if total_artifact_bytes > 50 * 1024 * 1024:
        raise ValueError("artifact references exceed 50MB budget; use external references")
    return {
        "source_agent_id": handoff.source_agent_id,
        "target_agent_id": handoff.target_agent_id,
        "task_id": handoff.task_id,
        "objective": handoff.objective,
        "completed_work": sanitize_dict(dict(handoff.completed_work)),
        "pending_work": sanitize_dict(dict(handoff.pending_work)),
        "decisions": list(handoff.decisions),
        "assumptions": list(handoff.assumptions),
        "constraints": list(handoff.constraints),
        "artifacts": artifacts,
        "references": list(handoff.references),
        "warnings": list(handoff.warnings),
        "known_failures": list(handoff.known_failures),
        "acceptance_criteria": list(handoff.acceptance_criteria),
        "next_action": handoff.next_action,
        "mode": handoff.mode.value,
        "context_rule": handoff.context_rule.value,
        "relevant_context": transferred,
        "context_manifest": {
            "included_items": manifest.included_items,
            "excluded_items": manifest.excluded_items,
            "redacted_items": manifest.redacted_items,
            "source": manifest.source,
            "target": manifest.target,
            "policy": manifest.policy,
        },
    }
