"""Browser agent run: objective -> bounded task with risk policy.

High-risk steps return {requiresApproval: true} instead of executing;
the operator approves explicitly (human hook consumed by MP19).
"""

import os

from openagent.browser.client import BrowserClient

client = BrowserClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)

session = client.create_session()
page = client.create_page(session["session_id"], url="https://example.com")
task = client.create_task(
    session["id"],
    objective="Research the latest pricing information and return a structured comparison.",
)

# Read-only step: executes immediately.
print(client.act(task["id"], action_type="EXTRACT", page_id=page["id"],
                 input_data={"selector": "body"}))

# Mutating step without approval: parked, not executed.
parked = client.act(task["id"], action_type="UPLOAD", page_id=page["id"],
                    input_data={"selector": "#file", "files": []})
print("parked:", parked)
assert parked.get("requiresApproval") is True

client.close()
