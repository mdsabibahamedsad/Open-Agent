"""Browser nodes inside a workflow definition (validated, policy-aware).

Validates with the real production validator: browser_agent requires an
objective, browser_action requires a known action_type, browser_extract
requires a selector. Secrets may only appear as credential_id / {{refs}}.
"""

from openagent.services.workflow_definition import validate_definition

definition = {
    "schema_version": "1.0",
    "triggers": [{"id": "t1", "type": "manual", "name": "Run"}],
    "nodes": [
        {"id": "n1", "type": "browser_agent", "name": "Research",
         "config": {"objective": "Compare pricing across vendors",
                    "max_steps": 25, "allowed_domains": ["example.com"]}},
        {"id": "n2", "type": "browser_extract", "name": "Extract",
         "config": {"selector": "table.pricing", "multiple": True}},
    ],
    "edges": [{"id": "e1", "from": "t1", "to": "n1", "when": "always"},
              {"id": "e2", "from": "n1", "to": "n2", "when": "success"}],
}

result = validate_definition(definition)
print("valid:", result.valid)
for issue in result.errors:
    print("-", issue.code, issue.message)
