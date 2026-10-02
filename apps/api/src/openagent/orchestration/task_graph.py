"""Task-graph utilities: cycle detection, topo sort, ready-set, deadlock analysis."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from openagent.orchestration.types import DependencyPolicy, OrchTaskStatus


TERMINAL_TASK_STATUSES = {
    OrchTaskStatus.SUCCEEDED,
    OrchTaskStatus.FAILED,
    OrchTaskStatus.SKIPPED,
    OrchTaskStatus.CANCELLED,
    OrchTaskStatus.TIMED_OUT,
}

SUCCESS_STATUSES = {OrchTaskStatus.SUCCEEDED, OrchTaskStatus.SKIPPED}


@dataclass
class TaskNode:
    task_id: str
    dependencies: List[str]
    status: OrchTaskStatus = OrchTaskStatus.CREATED
    dependency_policy: DependencyPolicy = DependencyPolicy.ALL_SUCCESS


def find_cycle(nodes: Dict[str, TaskNode]) -> Optional[List[str]]:
    """Return a cycle path if present, else None. DFS-based."""
    visiting: Set[str] = set()
    visited: Set[str] = set()
    stack: List[str] = []

    def dfs(node_id: str) -> Optional[List[str]]:
        visiting.add(node_id)
        stack.append(node_id)
        node = nodes.get(node_id)
        if node:
            for dep in node.dependencies:
                if dep not in nodes:
                    continue
                if dep in visiting:
                    idx = stack.index(dep)
                    return stack[idx:] + [dep]
                if dep not in visited:
                    found = dfs(dep)
                    if found:
                        return found
        visiting.discard(node_id)
        visited.add(node_id)
        stack.pop()
        return None

    for node_id in nodes:
        if node_id not in visited:
            found = dfs(node_id)
            if found:
                return found
    return None


def topological_order(nodes: Dict[str, TaskNode]) -> List[str]:
    """Kahn's algorithm. Raises ValueError on cycle."""
    indegree: Dict[str, int] = {nid: 0 for nid in nodes}
    dependents: Dict[str, List[str]] = defaultdict(list)
    for nid, node in nodes.items():
        for dep in node.dependencies:
            if dep in nodes:
                indegree[nid] += 1
                dependents[dep].append(nid)
    queue: deque[str] = deque([nid for nid, d in indegree.items() if d == 0])
    order: List[str] = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for child in dependents[nid]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(order) != len(nodes):
        raise ValueError("task graph contains a cycle")
    return order


def graph_depth(nodes: Dict[str, TaskNode]) -> int:
    """Longest dependency chain length (1 for a single root)."""
    order = topological_order(nodes)
    depth: Dict[str, int] = {}
    for nid in order:
        node = nodes[nid]
        if not node.dependencies:
            depth[nid] = 1
        else:
            depth[nid] = 1 + max((depth.get(d, 0) for d in node.dependencies if d in depth), default=0)
    return max(depth.values(), default=0)


def dependencies_satisfied(
    node: TaskNode,
    statuses: Dict[str, OrchTaskStatus],
) -> bool:
    """Evaluate dependency policy against current statuses."""
    if not node.dependencies:
        return True
    dep_statuses = [statuses.get(d) for d in node.dependencies]
    # All deps must at least be terminal (or skipped) before evaluation, except
    # IGNORE_FAILURE which still requires terminality.
    if any(s is None or s not in TERMINAL_TASK_STATUSES for s in dep_statuses):
        return False
    assert all(s is not None for s in dep_statuses)
    successes = sum(1 for s in dep_statuses if s in SUCCESS_STATUSES)
    total = len(dep_statuses)
    if node.dependency_policy == DependencyPolicy.ALL_SUCCESS:
        return successes == total
    if node.dependency_policy == DependencyPolicy.ANY_SUCCESS:
        return successes >= 1
    if node.dependency_policy == DependencyPolicy.ALLOW_PARTIAL:
        return successes >= 1
    if node.dependency_policy == DependencyPolicy.IGNORE_FAILURE:
        return True
    return False


def compute_ready(nodes: Dict[str, TaskNode]) -> List[str]:
    """Task ids in CREATED state whose dependencies are satisfied."""
    statuses = {nid: n.status for nid, n in nodes.items()}
    ready = []
    for nid, node in nodes.items():
        if node.status == OrchTaskStatus.CREATED and dependencies_satisfied(node, statuses):
            ready.append(nid)
    return ready


def detect_deadlock(nodes: Dict[str, TaskNode]) -> Optional[str]:
    """Detect unsatisfiable waits: missing deps or failed deps under ALL_SUCCESS."""
    for nid, node in nodes.items():
        if node.status in TERMINAL_TASK_STATUSES:
            continue
        for dep in node.dependencies:
            if dep not in nodes:
                return f"task {nid} depends on unknown task {dep}"
    cycle = find_cycle(nodes)
    if cycle:
        return f"dependency cycle: {' -> '.join(cycle)}"
    return None


def should_fail_parent(node: TaskNode, statuses: Dict[str, OrchTaskStatus]) -> bool:
    """Whether a parent blocked by this policy must fail when deps settle."""
    dep_statuses = [statuses.get(d) for d in node.dependencies]
    if any(s is None or s not in TERMINAL_TASK_STATUSES for s in dep_statuses):
        return False
    successes = sum(1 for s in dep_statuses if s in SUCCESS_STATUSES)
    if node.dependency_policy == DependencyPolicy.ALL_SUCCESS:
        return successes != len(dep_statuses)
    if node.dependency_policy in (DependencyPolicy.ANY_SUCCESS, DependencyPolicy.ALLOW_PARTIAL):
        return successes == 0
    return False
