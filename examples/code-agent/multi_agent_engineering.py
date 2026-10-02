"""Multi-agent engineering: fan out independent tasks, then aggregate.

Frontend, backend, and test work run in SEPARATE workspaces/branches so no
two agents write to the same checkout. A manager (human or orchestration
run) tracks the dependency graph and merges results.
"""

import os

from openagent.code.client import CodeClient

client = CodeClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)
repository_id = os.environ["OPENAGENT_REPOSITORY_ID"]

workstreams = {
    "backend": "Implement the /api/v1/rate-limits endpoint with storage backend",
    "frontend": "Add the rate-limit settings panel under /settings with API wiring",
    "tests": "Add integration tests covering the rate-limit endpoint and panel",
}

tasks = {}
for name, objective in workstreams.items():
    t = client.create_task(repository_id=repository_id, objective=objective,
                           max_steps=60, branch=f"openagent/task/{name}")
    tasks[name] = t
    print(f"{name}: task {t['task_id']} on branch {t.get('branch')}")

results = {}
for name, t in tasks.items():
    final = client.wait(t["id"], timeout_s=2400.0)
    results[name] = final["status"]
    print(f"{name}: {final['status']}")

failed = {k: v for k, v in results.items() if v not in ("SUCCEEDED", "READY_FOR_PR")}
if failed:
    raise SystemExit(f"workstreams failed: {failed}")

for name, t in tasks.items():
    review = client.review_task(t["id"])
    blocking = [f for f in review.get("findings", [])
                if f["severity"] in ("HIGH", "CRITICAL")]
    print(f"{name}: review {review.get('status')}, blocking={len(blocking)}")

client.close()
