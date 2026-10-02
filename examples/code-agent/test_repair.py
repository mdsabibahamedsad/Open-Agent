"""Failed-test loop: run tests -> analyze failure -> fix -> retest (bounded).

Runs the repository's targeted tests through the TEST execution profile,
prints normalized results, and leaves the fix to a bounded coding task.
"""

import os

from openagent.code.client import CodeClient

client = CodeClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)
repository_id = os.environ["OPENAGENT_REPOSITORY_ID"]

ws = client.create_workspace(repository_id)
print("workspace:", ws["workspace_id"], ws["status"])

result = client.run_tests("pytest tests/unit/test_auth.py -x -q",
                          workspace_id=ws["id"])
print("status:", result.get("status"), "exit:", result.get("exit_code"))
print("passed:", result.get("passed"), "failed:", result.get("failed"))

if result.get("failed"):
    task = client.create_task(
        repository_id=repository_id,
        objective=("Fix the failing tests in tests/unit/test_auth.py: "
                   "reproduce, patch the implementation, add a regression test, retest"),
        max_steps=40,
    )
    print("fix task:", task["task_id"])
    final = client.wait(task["id"], timeout_s=1800.0)
    print("fix final:", final["status"])

client.close()
