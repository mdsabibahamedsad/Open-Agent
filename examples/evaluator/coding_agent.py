"""Example — Coding agent: edit -> sandbox tests -> verify -> gate -> correct.

Code Agent -> edit repository -> sandbox build/tests -> static checks ->
evaluator -> failure analysis -> correction -> retest -> quality gate.

Requires a running API and env:
  OPENAGENT_API_URL, OPENAGENT_API_KEY, OPENAGENT_ORG_ID, OPENAGENT_CODE_TASK_ID
"""

import json
import os
import urllib.request

BASE = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000")
ORG = os.environ["OPENAGENT_ORG_ID"]
KEY = os.environ.get("OPENAGENT_API_KEY", "")
TASK = os.environ["OPENAGENT_CODE_TASK_ID"]


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


# 1. Verify the task from observable evidence (tests + secrets + diff).
outcome = call("POST", f"/api/v1/code/tasks/{TASK}/verify", {})
print("code decision:", outcome["decision"], outcome["score"])
print("reasons:", outcome["reason_codes"])

# 2. Enforce the build gate (no side effects; approval checked read-only).
gate = call("POST", f"/api/v1/organizations/{ORG}/quality-gates/builtin:code_build_gate/evaluate", {
    "check_targets": {
        # Real targets come from the sandbox run; placeholders fail closed.
        "build_tests": {"passed": 12, "failed": 0},
        "no_secrets": {"findings": []},
    },
    "score": outcome["score"],
})
print("gate passed:", gate["passed"], "failed:", gate["failed_checks"])
assert gate["passed"] is True

# 3. On FAIL the agent corrects via a NEW evaluation — never by editing history.
if outcome["decision"] == "FAIL":
    plan = call("POST",
                f"/api/v1/organizations/{ORG}/evaluations/{outcome['evaluation_id']}/correct",
                {"strategy": "RETRY_WITH_BACKOFF"})
    print("retry plan:", plan["plan_id"], plan["strategy"])
