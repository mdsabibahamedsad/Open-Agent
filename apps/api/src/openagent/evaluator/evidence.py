"""Tamper-resistant evidence system (MP20).

Evidence is captured with provenance + content hash at capture time and
treated as immutable afterwards. Model-generated claims are labeled as such
and never equivalent to system-verified evidence. Secrets are redacted via
the canonical approvals redaction (no second implementation).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from openagent.approvals.hashing import canonical_json, redact_params
from openagent.evaluator.types import EvidenceRecord, EvidenceTrust, EvidenceType


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(content: Any) -> str:
    return hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


def classify_trust(source_type: str) -> EvidenceTrust:
    """Server-side trust classification. The evaluated agent cannot self-label
    its output as verified: AGENT_OUTPUT/MODEL_RESPONSE are always
    MODEL_GENERATED regardless of what the agent claims."""
    normalized = (source_type or "").upper()
    if normalized in ("SYSTEM", "VERIFIER", "WORKFLOW_ENGINE", "SANDBOX_RUNNER",
                      "TEST_RUNNER", "DB", "DATABASE"):
        return EvidenceTrust.SYSTEM_VERIFIED
    if normalized in ("TOOL", "TOOL_RUNTIME", "PROVIDER", "MCP_TOOL"):
        return EvidenceTrust.TOOL_VERIFIED
    if normalized in ("EXTERNAL", "WEBHOOK", "API"):
        return EvidenceTrust.EXTERNAL_VERIFIED
    if normalized in ("USER", "HUMAN", "REVIEWER"):
        return EvidenceTrust.USER_CONFIRMED
    if normalized in ("AGENT_OUTPUT", "MODEL", "MODEL_RESPONSE", "AGENT"):
        return EvidenceTrust.MODEL_GENERATED
    return EvidenceTrust.UNVERIFIED


class EvidenceCollector:
    """In-memory builder; the engine persists records durably."""

    def __init__(self, *, organization_id: str = "", execution_id: str = "",
                 agent_id: str = ""):
        self.organization_id = organization_id
        self.execution_id = execution_id
        self.agent_id = agent_id
        self._records: list[EvidenceRecord] = []

    def add(self, evidence_type: EvidenceType, content: Any, *,
            source: str = "", source_type: str = "", source_id: str = "",
            tool_id: str = "", trust: Optional[EvidenceTrust] = None) -> EvidenceRecord:
        redacted = redact_params(content if isinstance(content, (dict, list)) else {"value": content})
        record = EvidenceRecord(
            evidence_type=evidence_type,
            trust=trust or classify_trust(source_type or source),
            content=redacted if isinstance(redacted, dict) else {"value": redacted},
            source=source[:256], source_type=(source_type or "")[:64],
            source_id=(source_id or "")[:256], execution_id=self.execution_id[:128],
            tool_id=(tool_id or "")[:256], agent_id=self.agent_id[:128],
            content_hash=content_hash(redacted), captured_at=_utcnow_iso())
        self._records.append(record)
        return record

    def records(self) -> list[EvidenceRecord]:
        return list(self._records)

    def by_type(self, evidence_type: EvidenceType) -> list[EvidenceRecord]:
        return [r for r in self._records if r.evidence_type == evidence_type]

    def best_trust(self) -> EvidenceTrust:
        from openagent.evaluator.types import TRUST_RANK
        best = EvidenceTrust.UNVERIFIED
        for record in self._records:
            if TRUST_RANK[record.trust] > TRUST_RANK[best]:
                best = record.trust
        return best


def verify_content_hash(record: EvidenceRecord) -> bool:
    """Detect post-capture tampering of an evidence record."""
    try:
        return content_hash(record.content) == record.content_hash
    except Exception:
        return False
