"""Regenerate docs/chat-tools.md from the koro TOOL_SCHEMAS table.

Parses `apps/api/src/openagent/api/v1/koro_tools/registry.py` with the ast
module so it runs without importing the application or its dependencies.
Example user messages live in EXAMPLES below.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY_PY = REPO / "apps/api/src/openagent/api/v1/koro_tools/registry.py"
DOC = REPO / "docs/chat-tools.md"

# One short example user message per tool.
EXAMPLES = {
    "list": "List all my workflows and their status.",
    "inspect": "Show me the latest run of the onboarding workflow.",
    "explain": "Explain what the daily-report workflow does, node by node.",
    "diagnose": "Why did the last run of this workflow fail?",
    "create": "Create a new draft workflow called email-digest.",
    "build": "Build a workflow from this definition: { ... }",
    "edit": "Replace the current workflow definition with this one.",
    "update_workflow": "Rename this workflow to weekly-summary.",
    "duplicate": "Duplicate the onboarding workflow.",
    "delete": "Delete the test-workflow workflow.",
    "publish": "Publish this workflow so its webhook is live.",
    "unpublish": "Take this workflow back to draft.",
    "versions": "Show the saved versions of this workflow.",
    "restore": "Restore version 3 as a new draft.",
    "undo_last": "Undo the last change to this workflow.",
    "export_workflow": "Export this workflow as JSON.",
    "import_workflow": "Import this workflow definition.",
    "add_node": "Add a Filter node after the webhook.",
    "update_node": "Set the Filter node's condition to status equals active.",
    "remove_node": "Remove the Set node.",
    "connect": "Connect the webhook node to the filter node.",
    "disconnect": "Disconnect the filter from the email node.",
    "test_node": "Run just the filter node and show its output.",
    "node_coverage": "Can you build a workflow that posts to Slack?",
    "link_subworkflow": "Link this Subworkflow node to the utils workflow.",
    "set_workflow_setting": "Set the workflow timeout to five minutes.",
    "set_node_settings": "Enable retry on the HTTP node.",
    "schedule": "Schedule this workflow to run every day at 9am.",
    "set_schedule": "Set the schedule trigger to run every day at 9am.",
    "set_static_data": "Store the last sync timestamp as workflow static data.",
    "variables": "What variables does this workflow declare?",
    "set_variable": "Set the region variable to eu-west.",
    "run": "Run this workflow now and summarize the result.",
    "runs": "Show the last ten runs across my workflows.",
    "node_logs": "Show the per-node logs for the latest run.",
    "retry": "Retry the failed run from earlier today.",
    "cancel": "Cancel the running execution.",
    "resume_wait": "Resume the execution waiting on the approval node.",
    "list_credentials": "Which credentials do I have configured?",
    "list_agents": "List my agents and their status.",
    "create_agent": "Create an agent named researcher that uses web search.",
    "webhook_url": "What is this workflow's production webhook URL?",
    "operations_status": "How is the platform doing? Any queued executions?",
    "prune": "Prune executions older than 30 days.",
    "health": "Show the platform health snapshot.",
    "open_page": "Open this workflow's page.",
}


def load_tool_specs(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        value = None
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "TOOL_SCHEMAS" for t in node.targets
        ):
            value = node.value
        elif isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "TOOL_SCHEMAS":
            value = node.value
        if value is None:
            continue
        tools = []
        for elt in value.elts:
            if not (isinstance(elt, ast.Call) and getattr(elt.func, "id", "") == "ToolSpec"):
                continue
            pos = [ast.literal_eval(a) for a in elt.args[:5]]
            kw = {
                k.arg: ast.literal_eval(k.value)
                for k in elt.keywords
                if k.arg in ("requires_confirmation", "returns_undo")
            }
            tools.append(
                {
                    "name": pos[0],
                    "domain": pos[1],
                    "kind": pos[2],
                    "permission": pos[3],
                    "description": pos[4],
                    "requires_confirmation": kw.get("requires_confirmation", False),
                    "returns_undo": kw.get("returns_undo", False),
                }
            )
        return tools
    raise SystemExit("TOOL_SCHEMAS not found in %s" % path)


def main():
    tools = sorted(load_tool_specs(REGISTRY_PY), key=lambda t: (t["domain"], t["name"]))
    missing = {t["name"] for t in tools} - set(EXAMPLES)
    if missing:
        raise SystemExit("EXAMPLES missing for: %s" % ", ".join(sorted(missing)))

    rows = [
        "| Tool | Domain | Kind | Permission | Example user message | Confirm | Undo |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in tools:
        example = EXAMPLES[t["name"]].replace("|", "\\|")
        rows.append(
            "| `%s` | %s | %s | `%s` | \"%s\" | %s | %s |"
            % (
                t["name"],
                t["domain"],
                t["kind"],
                t["permission"],
                example,
                "yes" if t["requires_confirmation"] else "\u2014",
                "yes" if t["returns_undo"] else "\u2014",
            )
        )

    doc = (
        "# Chat tools\n\n"
        "The assistant can plan and run the tools below. This page is generated from\n"
        "`apps/api/src/openagent/api/v1/koro_tools/registry.py` (`TOOL_SCHEMAS`, the\n"
        "same source that feeds `GET /api/v1/organizations/{org}/copilot/tools`) by\n"
        "`scripts/generate_chat_tools_docs.py`.\n\n"
        "- `kind`: `read` never changes state; `write` changes state; `destructive`\n"
        "  removes data (run history is kept for audit where noted).\n"
        "- `Confirm`: the tool asks for confirmation before it runs.\n"
        "- `Undo`: the tool returns an undo handle that `undo_last` can revert.\n\n"
        + "\n".join(rows)
        + "\n"
    )
    DOC.write_text(doc, encoding="utf-8")
    print("updated %s: %d tools" % (DOC, len(tools)))


if __name__ == "__main__":
    main()
