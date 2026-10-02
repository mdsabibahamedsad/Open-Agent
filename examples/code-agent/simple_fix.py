"""Simple bug fix: create task -> wait -> inspect diff -> review.

Uses only the canonical API (policy-aware). Requires a running API
(`docker compose up`) and an API key with code access.
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
    objective="Fix the off-by-one error in session expiry validation",
    max_steps=25,
)
print("task:", task["task_id"], task["status"])

final = client.wait(task["id"], timeout_s=1200.0)
print("final:", final["status"], f"step {final['current_step']}/{final['max_steps']}")

diff = client.task_diff(task["id"])
files = diff.get("files", [])
print(f"changed files: {len(files)}")
for f in files[:20]:
    print(" -", f.get("path"), f"+{f.get('additions', 0)}/-{f.get('deletions', 0)}")

review = client.review_task(task["id"])
print("review:", review.get("status"))
for finding in review.get("findings", [])[:10]:
    print(f"  [{finding['severity']}] {finding.get('file', '')}: {finding['finding'][:120]}")

if final["status"] not in ("SUCCEEDED", "READY_FOR_PR"):
    sys.exit(f"task did not succeed: {final['status']}")

client.close()
