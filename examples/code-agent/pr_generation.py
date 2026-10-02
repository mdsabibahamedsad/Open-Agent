"""PR generation: diff -> review gate -> commit -> push (approved) -> PR draft."""

import os
import sys

from openagent.code.client import CodeClient

client = CodeClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)

task_id = os.environ["OPENAGENT_TASK_ID"]

diff = client.task_diff(task_id)
if not diff.get("files"):
    sys.exit("no changes to propose")

review = client.review_task(task_id)
blocking = [f for f in review.get("findings", []) if f["severity"] in ("HIGH", "CRITICAL")]
if blocking:
    for f in blocking:
        print(f"BLOCKED [{f['severity']}] {f['finding'][:160]}")
    sys.exit("resolve blocking findings first")

commit = client.commit(task_id, os.environ.get(
    "OPENAGENT_COMMIT_MESSAGE", "fix: address review findings"))
print("commit:", commit.get("revision"))

push = client.push(task_id, approved=True)
print("push:", push)

pr = client.prepare_pr(task_id, os.environ.get("OPENAGENT_PR_TITLE", "Proposed changes"),
                       summary=os.environ.get("OPENAGENT_PR_SUMMARY", ""),
                       open=os.environ.get("OPENAGENT_PR_OPEN", "false").lower() == "true")
print("pr:", pr.get("id"), pr.get("status"))

client.close()
