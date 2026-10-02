"""MP22: resource dependency graph + impact analysis.

Builds the install-time resource graph::

    Workforce
    +-- Manager Agent (+ Skill, Model Preset, Memory Preset)
    +-- Worker Agents (+ Browser / Code Skill / Sandbox)
    +-- Workflow (+ Connectors)
    +-- Connectors / Tools / Policies

Supports traversal, cycle-safe topological ordering, Mermaid visualization
(for the workforce builder UI) and update impact analysis (what changes,
who depends on it, permission/security deltas).
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


def build_graph(
    resources: list[dict[str, Any]],
    dependencies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build ``{nodes, edges}`` from manifest resources + dependencies."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    def node_id(kind: str, slug: str) -> str:
        return f"{kind}:{slug}"

    for resource in resources:
        kind = str(resource.get("kind", "RESOURCE"))
        slug = str(resource.get("slug", ""))
        nid = node_id(kind, slug)
        nodes[nid] = {
            "id": nid,
            "kind": kind,
            "slug": slug,
            "name": str(resource.get("name", slug)),
        }
        payload = resource.get("payload", {}) if isinstance(resource.get("payload"), dict) else {}
        for rel_key in ("skills", "tools", "connectors", "agents", "workflows",
                        "model_preset", "memory_preset", "requires"):
            related = payload.get(rel_key)
            if isinstance(related, str):
                related = [related]
            if not isinstance(related, list):
                continue
            for item in related:
                if not isinstance(item, str) or not item:
                    continue
                target_kind = rel_key.rstrip("s").upper()
                target = node_id(target_kind, item)
                nodes.setdefault(target, {"id": target, "kind": target_kind,
                                          "slug": item, "name": item})
                edges.append({"from": nid, "to": target, "relation": rel_key})
    for dep in dependencies or []:
        if not isinstance(dep, dict):
            continue
        target = node_id(str(dep.get("type", "package")).upper(), str(dep.get("package", "")))
        nodes.setdefault(target, {"id": target,
                                  "kind": str(dep.get("type", "package")).upper(),
                                  "slug": str(dep.get("package", "")),
                                  "name": str(dep.get("package", ""))})
        edges.append({"from": "package:root", "to": target, "relation": "depends_on"})
    nodes.setdefault("package:root", {"id": "package:root", "kind": "PACKAGE",
                                      "slug": "root", "name": "Package"})
    return {"nodes": list(nodes.values()), "edges": edges}


def topological_order(graph: dict[str, Any]) -> list[str]:
    """Dependencies-first ordering; raises ValueError on cycles."""
    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, list[str]] = defaultdict(list)
    ids = [node["id"] for node in graph.get("nodes", [])]
    for edge in graph.get("edges", []):
        outgoing[edge["to"]].append(edge["from"])
        incoming[edge["from"]] += 1
        incoming.setdefault(edge["to"], incoming.get(edge["to"], 0))
    queue: deque[str] = deque([nid for nid in ids if incoming.get(nid, 0) == 0])
    order: list[str] = []
    while queue:
        current = queue.popleft()
        order.append(current)
        for dependent in outgoing.get(current, []):
            incoming[dependent] -= 1
            if incoming[dependent] == 0:
                queue.append(dependent)
    if len(order) != len(ids):
        raise ValueError("circular dependency in resource graph")
    return order


def to_mermaid(graph: dict[str, Any]) -> str:
    """Render the graph as a Mermaid flowchart for the builder UI."""
    lines = ["flowchart TD"]
    safe = {node["id"]: f"n{index}" for index, node in enumerate(graph.get("nodes", []))}
    for node in graph.get("nodes", []):
        label = f"{node['kind']}: {node['name']}".replace('"', "'")
        lines.append(f'    {safe[node["id"]]}["{label}"]')
    for edge in graph.get("edges", []):
        if edge["from"] in safe and edge["to"] in safe:
            lines.append(f"    {safe[edge['from']]} -->|{edge['relation']}| {safe[edge['to']]}")
    return "\n".join(lines)


def analyze_impact(
    old_manifest: dict[str, Any],
    new_manifest: dict[str, Any],
    dependents: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Impact analysis for an update: deltas + affected dependents."""
    from openagent.packages.packaging import diff_manifests

    diff = diff_manifests(old_manifest, new_manifest)
    permission_changed = bool(
        diff["permission_changes"]["approvals_added"]
        or diff["permission_changes"]["approvals_removed"]
    )
    breaking = permission_changed or bool(diff["dependency_changes"]["removed"])
    affected = dependents or []
    return {
        "diff": diff,
        "breaking": breaking,
        "permission_changed": permission_changed,
        "security_changed": diff["security_changed"],
        "affected_dependents": affected,
        "affected_count": len(affected),
        "summary": (
            f"{len(diff['added_resources'])} added, "
            f"{len(diff['removed_resources'])} removed, "
            f"{len(diff['changed_resources'])} changed; "
            f"{len(affected)} dependent(s) affected"
        ),
    }
