"""Example — Research agent with citation verification and correction.

Research Agent -> collect sources -> generate answer -> verify citations and
completeness -> FAIL -> correction (expand context) -> re-evaluate -> PASS.

Requires a running API (`docker compose up`) and env:
  OPENAGENT_API_URL, OPENAGENT_API_KEY, OPENAGENT_ORG_ID
"""

import json
import os
import urllib.request

BASE = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000")
ORG = os.environ["OPENAGENT_ORG_ID"]
KEY = os.environ.get("OPENAGENT_API_KEY", "")


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


answer = {"summary": "Quantum batteries charge faster [1][2].",
          "citations": ["doi:10.xxxx/a", "doi:10.xxxx/b"]}

# 1. Create the evaluation with research criteria + collected evidence.
evaluation = call("POST", f"/api/v1/organizations/{ORG}/evaluations", {
    "evaluation_type": "COMPLETENESS",
    "goal": "Answer with supported citations for every claim",
    "criteria": [{"name": "citations_present", "method": "output_contains"},
                 {"name": "claims_supported", "method": "llm"}],
    "output_ref": answer,
    "evidence": [{"evidence_type": "AGENT_OUTPUT", "content": answer,
                  "source": "research_agent", "source_type": "AGENT_OUTPUT"}],
})
evaluation_id = evaluation["id"]

# 2. Deterministic first: citation markers present?
verified = call("POST",
                f"/api/v1/organizations/{ORG}/evaluations/{evaluation_id}/verify", {
                    "checks": [{"kind": "output_contains", "name": "citations_present",
                                "target": answer,
                                "params": {"contains": ["[1]", "doi:"]},
                                "required": True}]})
print("checks:", verified["checks"])

# 3. Finalize: PASS completes, FAIL plans a correction, UNCERTAIN asks a human.
outcome = call("POST",
               f"/api/v1/organizations/{ORG}/evaluations/{evaluation_id}/finalize",
               {"quality_threshold": 0.7})
print("decision:", outcome["decision"], outcome["score"], outcome.get("approval_id"))
assert outcome["decision"] in ("PASS", "FAIL", "UNCERTAIN")

if outcome["decision"] == "FAIL":
    plan = call("POST",
                f"/api/v1/organizations/{ORG}/evaluations/{evaluation_id}/correct",
                {"root_cause": {"symptom": outcome["failure_reason"]}})
    print("correction:", plan["strategy"], "approval_required:", plan["approval_required"])
