"""GitHub issue -> agent analysis -> Code Agent -> sandbox tests -> evaluator -> PR.

Requires a running API and env:
  OPENAGENT_API_URL, OPENAGENT_API_KEY, OPENAGENT_ORG_ID,
  OPENAGENT_GITHUB_CONNECTION_ID
"""

import json
import os
import urllib.request

BASE = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000")
ORG = os.environ["OPENAGENT_ORG_ID"]
KEY = os.environ.get("OPENAGENT_API_KEY", "")
GITHUB = os.environ["OPENAGENT_GITHUB_CONNECTION_ID"]


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(body or {}).encode(), method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {KEY}", "X-Organization-ID": ORG})
    with urllib.request.urlopen(req) as res:
        return json.load(res)


# 1. Read the issue (LOW risk, executes immediately).
issue = call(
    "POST",
    f"/api/v1/organizations/{ORG}/integration-connections/{GITHUB}/execute",
    {"action_id": "github.get_issue",
     "input": {"owner": "acme", "repo": "api", "number": 42}})
print("issue:", issue["status"])

# 2. ... agent analyzes, Code Agent patches, sandbox runs tests (elsewhere) ...

# 3. Open the PR (MEDIUM, verified side effect: PR number returned).
pr = call(
    "POST",
    f"/api/v1/organizations/{ORG}/integration-connections/{GITHUB}/execute",
    {"action_id": "github.create_pr",
     "input": {"owner": "acme", "repo": "api", "title": "Fix #42",
               "head": "fix-42", "base": "main"}})
print("pr:", pr["status"], pr.get("result"))

# 4. Merging is HIGH risk: parks for human approval, never auto-merges.
merge = call(
    "POST",
    f"/api/v1/organizations/{ORG}/integration-connections/{GITHUB}/execute",
    {"action_id": "github.merge_pr",
     "input": {"owner": "acme", "repo": "api", "number": 7,
               "merge_method": "squash"}})
print("merge gate:", merge.get("status"), merge.get("approval_id"))
assert merge.get("status") == "WAITING_FOR_APPROVAL"
