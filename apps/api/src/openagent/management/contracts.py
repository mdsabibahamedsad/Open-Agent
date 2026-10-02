"""Agent contracts: structured work agreements (not permission grants).

A contract describes work requirements and boundaries. Permissions always
come from RBAC/policy/credential authorization — never from the contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openagent.management.types import AcceptanceCriterion


@dataclass
class AgentContract:
    objective: str
    responsibilities: List[str] = field(default_factory=list)
    inputs: Dict[str, Any] = field(default_factory=dict)
    expected_outputs: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)  # required (not granted)
    budget: Dict[str, Any] = field(default_factory=dict)
    deadline: Optional[str] = None  # ISO-8601
    quality_requirements: List[str] = field(default_factory=list)
    acceptance_criteria: List[AcceptanceCriterion] = field(default_factory=list)
    escalation_conditions: List[str] = field(default_factory=list)
    max_revisions: int = 3


@dataclass
class ContractValidation:
    valid: bool
    errors: List[str]


def validate_contract(contract: AgentContract) -> ContractValidation:
    errors: List[str] = []
    if not contract.objective or not contract.objective.strip():
        errors.append("objective must not be empty")
    if not contract.responsibilities:
        errors.append("at least one responsibility is required")
    if not contract.expected_outputs:
        errors.append("expected_outputs must describe the deliverable")
    if not contract.acceptance_criteria:
        errors.append("acceptance_criteria required for reviewable work")
    for criterion in contract.acceptance_criteria:
        if not criterion.description or not criterion.description.strip():
            errors.append("acceptance criterion description must not be empty")
    if contract.max_revisions < 0 or contract.max_revisions > 10:
        errors.append("max_revisions must be within 0..10")
    # Secret hygiene: contracts must never carry credentials.
    from openagent.orchestration.security import contains_secret_key

    def _scan(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if contains_secret_key(str(key)):
                    errors.append(f"secret-like key in contract at {path}.{key}")
                _scan(value, f"{path}.{key}")
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                _scan(value, f"{path}[{i}]")

    _scan(contract.inputs, "inputs")
    _scan(contract.expected_outputs, "expected_outputs")
    return ContractValidation(valid=not errors, errors=errors)


def contract_to_dict(contract: AgentContract) -> Dict[str, Any]:
    return {
        "objective": contract.objective,
        "responsibilities": list(contract.responsibilities),
        "inputs": dict(contract.inputs),
        "expected_outputs": dict(contract.expected_outputs),
        "capabilities": list(contract.capabilities),
        "constraints": list(contract.constraints),
        "permissions": list(contract.permissions),
        "budget": dict(contract.budget),
        "deadline": contract.deadline,
        "quality_requirements": list(contract.quality_requirements),
        "acceptance_criteria": [
            {"description": c.description, "verification": c.verification,
             "satisfied": c.satisfied}
            for c in contract.acceptance_criteria
        ],
        "escalation_conditions": list(contract.escalation_conditions),
        "max_revisions": contract.max_revisions,
    }


def contract_from_dict(data: Dict[str, Any]) -> AgentContract:
    criteria = [
        AcceptanceCriterion(
            description=str(c.get("description", "")),
            verification=str(c.get("verification", "")),
            satisfied=c.get("satisfied"),
        )
        for c in (data.get("acceptance_criteria") or [])
        if isinstance(c, dict)
    ]
    return AgentContract(
        objective=str(data.get("objective", "")),
        responsibilities=list(data.get("responsibilities", []) or []),
        inputs=dict(data.get("inputs", {}) or {}),
        expected_outputs=dict(data.get("expected_outputs", {}) or {}),
        capabilities=list(data.get("capabilities", []) or []),
        constraints=list(data.get("constraints", []) or []),
        permissions=list(data.get("permissions", []) or []),
        budget=dict(data.get("budget", {}) or {}),
        deadline=data.get("deadline"),
        quality_requirements=list(data.get("quality_requirements", []) or []),
        acceptance_criteria=criteria,
        escalation_conditions=list(data.get("escalation_conditions", []) or []),
        max_revisions=int(data.get("max_revisions", 3)),
    )
