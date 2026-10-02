"""Execution planner: builds an executable plan from a workflow definition."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from openagent.runtime.models import (
    ExecutionPlan,
    NodeExecutionPlan,
    NodeRunStatus,
    TriggerType,
    WorkflowRunStatus,
)
from openagent.services.workflow_definition import (
    NODE_TYPES,
    TRIGGER_TYPES,
    TERMINAL_NODE_TYPES,
    FAN_IN_NODE_TYPES,
    empty_definition,
    validate_definition,
)


class PlanningError(Exception):
    """Raised when planning fails."""
    def __init__(self, message: str, errors: list = None):
        super().__init__(message)
        self.errors = errors or []


def build_execution_plan(
    workflow_id: str,
    workflow_version_id: str,
    definition: dict,
    trigger_input: Optional[Dict[str, Any]] = None,
) -> ExecutionPlan:
    """
    Build an executable plan from a workflow definition.

    Validates the definition and constructs an execution plan with
    topological ordering for parallel execution.
    """
    # Validate the definition first
    result = validate_workflow_definition(definition)
    if not result.valid:
        raise PlanningError("Workflow definition is invalid", result.errors)

    # Build node map
    nodes_by_id = {n["id"]: n for n in definition.get("nodes", [])}
    triggers = definition.get("triggers", [])
    edges = definition.get("edges", [])
    variables = definition.get("variables", [])
    settings = definition.get("settings", {})

    # Build node execution plans
    node_plans = []
    for node in definition.get("nodes", []):
        plan = _create_node_plan(node)
        node_plans.append(plan)

    # Build edges
    edge_plans = []
    for edge in edges:
        edge_plans.append({
            "id": edge.get("id", f"edge_{uuid4().hex[:8]}"),
            "from": edge["from"],
            "to": edge["to"],
            "label": edge.get("label"),
            "condition": edge.get("condition", {"when": "always"}),
        })

    # Build trigger plans
    trigger_plans = []
    for trigger in triggers:
        trigger_plans.append({
            "id": trigger["id"],
            "type": trigger["type"],
            "name": trigger["name"],
            "config": trigger.get("config", {}),
        })

    # Build trigger map
    trigger_ids = [t["id"] for t in trigger_plans]

    # Compute topological ordering
    execution_order = _compute_execution_order(node_plans, edges)

    # Identify special node sets
    terminal_node_ids = {n.node_id for n in node_plans if n.node_id in _get_terminal_nodes(node_plans)}
    fan_in_node_ids = {n.node_id for n in node_plans if n.node_id in _get_fan_in_nodes(node_plans)}
    disabled_node_ids = {n.node_id for n in node_plans if n.is_disabled}

    # Create plan
    plan = ExecutionPlan(
        execution_id="",  # Will be set by caller
        workflow_id="",   # Will be set by caller
        workflow_version_id="",
        trigger=trigger_plans[0] if trigger_plans else {},
        nodes=node_plans,
        edges=edge_plans,
        variables=definition.get("variables", []),
        settings=definition.get("settings", {}),
        max_concurrency=definition.get("settings", {}).get("max_concurrency", 1),
        trigger_ids=[t["id"] for t in trigger_plans],
        terminal_node_ids=terminal_node_ids,
        fan_in_node_ids=fan_in_node_ids,
        disabled_node_ids=disabled_node_ids,
    )

    # Populate computed fields
    plan._compute_derived_fields()

    return plan


def _create_node_plan(node: Dict[str, Any]) -> NodeExecutionPlan:
    """Create a node execution plan from a node definition."""
    node_type = node["type"]
    return NodeExecutionPlan(
        node_id=node["id"],
        node_type=node_type,
        name=node.get("name", node_type),
        config=node.get("config", {}),
        position=node.get("position"),
        retry_policy=node.get("retry_policy"),
        timeout_seconds=node.get("timeout_seconds"),
        approval_required=node.get("approval_required", False),
        is_disabled=node.get("disabled", False),
        is_terminal=node["type"] in {"approval"},  # terminal nodes
    )


def _compute_execution_order(nodes: List[NodeExecutionPlan], edges: List[Dict[str, Any]]) -> List[List[str]]:
    """
    Compute topological execution order (levels of parallel execution).
    Returns list of levels, where each level contains node_ids that can run in parallel.
    """
    # Build adjacency and reverse adjacency
    node_ids = {n.node_id for n in nodes}
    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    indegree = {nid: 0 for nid in node_ids}

    for edge in edges:
        src, dst = edge["from"], edge["to"]
        if src in node_ids and dst in node_ids:
            outgoing[src].append(dst)
            incoming[dst].append(src)
            indegree[dst] += 1

    # Kahn's algorithm with level tracking
    queue = deque([nid for nid in node_ids if indegree[nid] == 0])
    levels = []

    while queue:
        level = []
        for _ in range(len(queue)):
            nid = queue.popleft()
            level.append(nid)
            for neighbor in outgoing[nid]:
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    queue.append(neighbor)
        if level:
            levels.append(level)

    # Check for cycles
    if sum(len(l) for l in levels) < len(node_ids):
        # There's a cycle - remaining nodes form a cycle
        remaining = [nid for nid in node_ids if indegree[nid] > 0]
        # For now, just add them as a final level (they'll fail at runtime)
        levels.append(remaining)

    return levels


def _get_terminal_nodes(nodes: List[NodeExecutionPlan]) -> Set[str]:
    """Get node IDs that are terminal (can end a branch)."""
    return {n.node_id for n in nodes if n.node_type in {"approval"}}


def _get_fan_in_nodes(nodes: List[NodeExecutionPlan]) -> Set[str]:
    """Get node IDs that accept fan-in (multiple inbound edges)."""
    return {n.node_id for n in nodes if n.node_type == "merge"}


# Import required modules
from collections import defaultdict, deque
from typing import Optional, Dict, List, Set, Tuple
from uuid import uuid4
from datetime import timezone

from openagent.runtime.models import (
    ExecutionPlan,
    NodeExecutionPlan,
    NodeRunStatus,
    TriggerType,
)
from openagent.services.workflow_definition import (
    NODE_TYPES,
    TRIGGER_TYPES,
    TERMINAL_NODE_TYPES,
    FAN_IN_NODE_TYPES,
    empty_definition,
    validate_definition,
)

# Add _compute_derived_fields to ExecutionPlan
def _compute_derived_fields(self) -> None:
    """Compute derived fields after plan creation."""
    self.node_map = {n.node_id: n for n in self.nodes}
    self.execution_order = _compute_execution_order(self.nodes, self.edges)
    self.trigger_ids = [t["id"] for t in self.trigger]
    self.terminal_node_ids = _get_terminal_nodes(self.nodes)
    self.fan_in_node_ids = _get_fan_in_nodes(self.nodes)
    self.disabled_node_ids = {n.node_id for n in self.nodes if n.is_disabled}

# Monkey-patch the method
ExecutionPlan._compute_derived_fields = _compute_derived_fields