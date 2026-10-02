"""Example — Multi-agent: workers -> evaluator -> manager -> human on UNCERTAIN.

CEO -> Research + Coding + Testing agents -> evaluator ->
  PASS -> manager | FAIL -> reassign/correct | UNCERTAIN -> human.

Requires a running API and env:
  OPENAGENT_API_URL, OPENAGENT_API_KEY, OPENAGENT_ORG_ID,
  OPENAGENT_ORCH_RUN_ID, OPENAGENT_ORCH_TASK_ID, OPENAGENT_EVALUATION_ID
"""

import json
import os
import urllib.request

BASE = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000")
ORG = os.environ["OPENAGENT_ORG_ID"]
KEY = os.environ.get("OPENAGENT_API_KEY", "")
RUN = os.environ["OPENAGENT_ORCH_RUN_ID"]
TASK = os.environ["OPENAGENT_ORCH_TASK_ID"]
EVALUATION = os.environ["OPENAGENT_EVALUATION_ID"]


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body or {}).encode(),
        method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {KEY}",
                 "X-Organization-ID": ORG},
    )
    with urllib.request.urlopen(req) as res:
        return json.load(res)


# Manager reviews the worker's evaluation — never the worker's bare claim.
review = call(
    "POST",
    f"/api/v1/organizations/{ORG}/orchestrations/{RUN}/tasks/{TASK}/review",
    {"evaluation_id": EVALUATION, "worker_agent_id": "testing-agent"})
print("recommendation:", review["recommendation"],
      "| verification:", review["verification_decision"])

if review["recommendation"] == "reassign":
    print("manager: reassign to another agent (bounded budgets apply)")
elif review["recommendation"] == "escalate":
    print("manager: route to human (UNCERTAIN stays visible)")
elif review["recommendation"] == "accept":
    print("manager: accept verified result")
else:
    print("manager: reject and replan")
