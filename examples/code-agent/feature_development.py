"""Full feature: plan -> multi-file task -> tests -> review -> commit -> PR draft.

Creates a coding task with explicit budgets, waits for completion, runs the
test plan, reviews the diff, commits on the task branch, and prepares a
(never auto-merged) PR draft.
"""

import os
import sys

from openagent.code.client import CodeClient

client = CodeClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)
repository_id = os.environ["OPENAGENT_REPOSITORY_ID"]

task = client.create_task(
    repository_id=repository_id,
    objective="Add rate limiting to the login endpoint with tests and docs",
    max_steps=80,
    risk_level="MEDIUM",
    budgets={"tool_calls": 200},
)
print("task:", task["task_id"], task["status"])

plan = client.task_plan(task["id"])
print("plan steps:")
for step in plan.get("steps", []):
    print(f"  {step['step']}. {step['title']}")

final = client.wait(task["id"], timeout_s=2400.0)
print("final:", final["status"])
if final["status"] not in ("SUCCEEDED", "READY_FOR_PR"):
    sys.exit(f"task did not succeed: {final['status']}")

tests = client.plan_tests(task["id"])
print("targeted:", tests.get("targeted"))
print("regression:", tests.get("regression"))

review = client.review_task(task["id"])
blocking = [f for f in review.get("findings", []) if f["severity"] in ("HIGH", "CRITICAL")]
if blocking:
    sys.exit(f"blocked by {len(blocking)} HIGH/CRITICAL findings")

commit = client.commit(task["id"], "feat(auth): rate-limit login endpoint")
print("commit:", commit.get("revision"))

pr = client.prepare_pr(task["id"], "Rate-limit login endpoint",
                       summary="Adds login rate limiting with tests and docs.")
print("pr:", pr.get("id"), pr.get("status"))

client.close()
