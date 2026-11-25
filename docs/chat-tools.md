# Chat tools

The assistant can plan and run the tools below. This page is generated from
`apps/api/src/openagent/api/v1/koro_tools/registry.py` (`TOOL_SCHEMAS`, the
same source that feeds `GET /api/v1/organizations/{org}/copilot/tools`) by
`scripts/generate_chat_tools_docs.py`.

- `kind`: `read` never changes state; `write` changes state; `destructive`
  removes data (run history is kept for audit where noted).
- `Confirm`: the tool asks for confirmation before it runs.
- `Undo`: the tool returns an undo handle that `undo_last` can revert.

| Tool | Domain | Kind | Permission | Example user message | Confirm | Undo |
|---|---|---|---|---|---|---|
| `create_agent` | agents | write | `agent:create` | "Create an agent named researcher that uses web search." | \u2014 | \u2014 |
| `list_agents` | agents | read | `agent:read` | "List my agents and their status." | \u2014 | \u2014 |
| `list_credentials` | credentials | read | `credential:read` | "Which credentials do I have configured?" | \u2014 | \u2014 |
| `add_node` | nodes | write | `workflow:update` | "Add a Filter node after the webhook." | \u2014 | yes |
| `connect` | nodes | write | `workflow:update` | "Connect the webhook node to the filter node." | \u2014 | yes |
| `disconnect` | nodes | write | `workflow:update` | "Disconnect the filter from the email node." | \u2014 | yes |
| `link_subworkflow` | nodes | write | `workflow:update` | "Link this Subworkflow node to the utils workflow." | \u2014 | yes |
| `node_coverage` | nodes | read | `workflow:read` | "Can you build a workflow that posts to Slack?" | \u2014 | \u2014 |
| `remove_node` | nodes | write | `workflow:update` | "Remove the Set node." | \u2014 | yes |
| `test_node` | nodes | write | `workflow:execute` | "Run just the filter node and show its output." | \u2014 | \u2014 |
| `update_node` | nodes | write | `workflow:update` | "Set the Filter node's condition to status equals active." | \u2014 | yes |
| `health` | operations | read | `workflow:read` | "Show the platform health snapshot." | \u2014 | \u2014 |
| `open_page` | operations | read | `workflow:read` | "Open this workflow's page." | \u2014 | \u2014 |
| `operations_status` | operations | read | `execution:read` | "How is the platform doing? Any queued executions?" | \u2014 | \u2014 |
| `prune` | operations | destructive | `workflow:update` | "Prune executions older than 30 days." | yes | \u2014 |
| `webhook_url` | operations | read | `workflow:read` | "What is this workflow's production webhook URL?" | \u2014 | \u2014 |
| `cancel` | runs | write | `workflow:execute` | "Cancel the running execution." | \u2014 | \u2014 |
| `node_logs` | runs | read | `execution:read` | "Show the per-node logs for the latest run." | \u2014 | \u2014 |
| `resume_wait` | runs | write | `workflow:execute` | "Resume the execution waiting on the approval node." | \u2014 | \u2014 |
| `retry` | runs | write | `workflow:execute` | "Retry the failed run from earlier today." | \u2014 | \u2014 |
| `run` | runs | write | `workflow:execute` | "Run this workflow now and summarize the result." | \u2014 | \u2014 |
| `runs` | runs | read | `execution:read` | "Show the last ten runs across my workflows." | \u2014 | \u2014 |
| `schedule` | settings | write | `workflow:update` | "Schedule this workflow to run every day at 9am." | \u2014 | yes |
| `set_node_settings` | settings | write | `workflow:update` | "Enable retry on the HTTP node." | \u2014 | yes |
| `set_schedule` | settings | write | `workflow:update` | "Set the schedule trigger to run every day at 9am." | \u2014 | yes |
| `set_static_data` | settings | write | `workflow:update` | "Store the last sync timestamp as workflow static data." | \u2014 | yes |
| `set_variable` | settings | write | `workflow:update` | "Set the region variable to eu-west." | \u2014 | yes |
| `set_workflow_setting` | settings | write | `workflow:update` | "Set the workflow timeout to five minutes." | \u2014 | yes |
| `variables` | settings | read | `workflow:read` | "What variables does this workflow declare?" | \u2014 | \u2014 |
| `build` | workflow | write | `workflow:create` | "Build a workflow from this definition: { ... }" | \u2014 | yes |
| `create` | workflow | write | `workflow:create` | "Create a new draft workflow called email-digest." | \u2014 | \u2014 |
| `delete` | workflow | destructive | `workflow:delete` | "Delete the test-workflow workflow." | yes | \u2014 |
| `diagnose` | workflow | read | `workflow:read` | "Why did the last run of this workflow fail?" | \u2014 | \u2014 |
| `duplicate` | workflow | write | `workflow:create` | "Duplicate the onboarding workflow." | \u2014 | \u2014 |
| `edit` | workflow | write | `workflow:update` | "Replace the current workflow definition with this one." | \u2014 | yes |
| `explain` | workflow | read | `workflow:read` | "Explain what the daily-report workflow does, node by node." | \u2014 | \u2014 |
| `export_workflow` | workflow | read | `workflow:read` | "Export this workflow as JSON." | \u2014 | \u2014 |
| `import_workflow` | workflow | write | `workflow:create` | "Import this workflow definition." | \u2014 | yes |
| `inspect` | workflow | read | `workflow:read` | "Show me the latest run of the onboarding workflow." | \u2014 | \u2014 |
| `list` | workflow | read | `workflow:read` | "List all my workflows and their status." | \u2014 | \u2014 |
| `publish` | workflow | write | `workflow:update` | "Publish this workflow so its webhook is live." | \u2014 | \u2014 |
| `restore` | workflow | destructive | `workflow:update` | "Restore version 3 as a new draft." | yes | yes |
| `undo_last` | workflow | write | `workflow:update` | "Undo the last change to this workflow." | \u2014 | yes |
| `unpublish` | workflow | write | `workflow:update` | "Take this workflow back to draft." | \u2014 | \u2014 |
| `update_workflow` | workflow | write | `workflow:update` | "Rename this workflow to weekly-summary." | \u2014 | \u2014 |
| `versions` | workflow | read | `workflow:read` | "Show the saved versions of this workflow." | \u2014 | \u2014 |
