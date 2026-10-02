"""Refactoring: search symbols, read callers, apply a patch, verify the diff.

Demonstrates the patch-first loop: find symbol -> find references -> read ->
propose unified diff -> inspect resulting diff.
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
    objective="Rename validate_session to check_session across the auth module",
    max_steps=30,
)
print("task:", task["task_id"])

ws_id = task.get("workspace_id")
if not ws_id:
    sys.exit("task has no workspace yet; retry after INITIALIZING")

symbols = client.search(ws_id, "validate_session", mode="symbol")
print("symbols:", len(symbols.get("results", [])))

refs = client.search(ws_id, "validate_session", mode="references")
for r in refs.get("results", [])[:10]:
    print(" ref:", r.get("path"), r.get("line"))

first = (symbols.get("results", []) or [{}])[0]
if first.get("path"):
    content = client.read_file(ws_id, first["path"], start=1, end=60)
    print("---", first["path"])
    print(content.get("content", "")[:1500])

print("diff:", client.task_diff(task["id"]))
client.close()
