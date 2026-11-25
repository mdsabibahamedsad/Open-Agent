"""Regenerate docs/workflows/nodes.md tables from the node registry JSON."""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "apps/api/src/openagent/registry/node-registry.json"
DOC = REPO / "docs/workflows/nodes.md"

CATEGORY_ORDER = ["Agents", "AI", "Logic", "Data", "Tools", "HTTP",
                  "Integrations", "Human", "Utilities", "Advanced"]


def ports(entry):
    ins = [p["name"] for p in entry.get("input_ports") or []]
    outs = [p["name"] for p in entry.get("output_ports") or []]
    if not ins:
        return ("\u2192 " + "/".join(outs)) if outs else "\u2014"
    left = " + ".join(ins)
    if len(ins) > 1:
        left += " (fan-in)"
    return (left + " \u2192 " + "/".join(outs)) if outs else left


def required_config(entry):
    keys = [f["key"] for f in entry.get("config_fields") or [] if f.get("required")]
    return " + ".join(f"`{k}`" for k in keys) if keys else "\u2014"


def main():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    nodes = sorted(
        registry["nodes"],
        key=lambda n: (CATEGORY_ORDER.index(n["category"])
                       if n["category"] in CATEGORY_ORDER else 99,
                       n["category"], n["type"]),
    )
    triggers = sorted(registry["triggers"], key=lambda t: t["type"])

    lines = ["| Type | Category | Ports | Required config |", "|---|---|---|---|"]
    for n in nodes:
        lines.append("| `%s` | %s | %s | %s |"
                     % (n["type"], n["category"], ports(n), required_config(n)))
    table = "\n".join(lines)

    tl = ["| Trigger | Ports | Required config |", "|---|---|---|"]
    for t in triggers:
        tl.append("| `%s` | %s | %s |" % (t["type"], ports(t), required_config(t)))
    trig_table = "\n".join(tl)

    section = (
        "## Node table (built-in, all `source: \"builtin\", `version: 1`)\n\n"
        "Regenerated from `apps/api/src/openagent/registry/node-registry.json` "
        "(`registry_version %s`) by `scripts/generate_node_docs.py`.\n\n"
        "%s\n\n"
        "### Triggers (%d)\n\n"
        "%s\n"
    ) % (registry.get("registry_version", "?"), table, len(triggers), trig_table)

    doc = DOC.read_text(encoding="utf-8")
    start = doc.index("## Node table")
    end = doc.index("## Connection model")
    DOC.write_text(doc[:start] + section + "\n" + doc[end:], encoding="utf-8")
    print("updated %s: %d nodes, %d triggers" % (DOC, len(nodes), len(triggers)))


if __name__ == "__main__":
    main()
