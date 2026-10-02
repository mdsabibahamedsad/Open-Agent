"""PostgreSQL query -> analysis -> verification -> report.

Read-only by default; writes need write mode + human approval. Credentials
never reach the model — only a credential_id travels with the request.

Requires a running API and env:
  OPENAGENT_API_URL, OPENAGENT_API_KEY, OPENAGENT_ORG_ID,
  OPENAGENT_POSTGRES_CONNECTION_ID
"""

import json
import os
import urllib.request

BASE = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000")
ORG = os.environ["OPENAGENT_ORG_ID"]
KEY = os.environ.get("OPENAGENT_API_KEY", "")
PG = os.environ["OPENAGENT_POSTGRES_CONNECTION_ID"]


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(body or {}).encode(), method=method,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {KEY}", "X-Organization-ID": ORG})
    with urllib.request.urlopen(req) as res:
        return json.load(res)


# 1. Parameterized read ($1 placeholders only — never string interpolation).
rows = call(
    "POST",
    f"/api/v1/organizations/{ORG}/integration-connections/{PG}/execute",
    {"action_id": "postgres.read",
     "input": {"sql": "SELECT id, total FROM orders WHERE status = $1 "
                      "ORDER BY total DESC LIMIT 25",
               "params": ["paid"], "max_rows": 25}})
print("rows:", rows.get("result", {}).get("row_count"),
      "truncated:", rows.get("result", {}).get("truncated"))

# 2. Analysis happens elsewhere; the report figures are verified evidence.
evaluation = call("POST", f"/api/v1/organizations/{ORG}/evaluations", {
    "evaluation_type": "CORRECTNESS",
    "goal": "Revenue report matches database rows",
    "output_ref": {"top_order_total": 42000},
    "evidence": [{"evidence_type": "TOOL_RESULT", "content": rows,
                  "source": "postgres.read", "source_type": "TOOL"}],
})
print("evaluation:", evaluation["id"], evaluation["status"])

# 3. A write would park for approval instead of executing:
# parked = call("POST", f"/api/v1/organizations/{ORG}/integration-connections/{PG}/execute",
#               {"action_id": "postgres.query",
#                "input": {"sql": "UPDATE orders SET status = $1 WHERE id = $2",
#                          "params": ["refunded", 7], "mode": "write"}})
# assert parked.get("status") == "WAITING_FOR_APPROVAL"
