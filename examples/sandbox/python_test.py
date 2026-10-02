"""Sandbox python-test: TEST profile, no network, redacted output.

Requires a running API (`docker compose up`) and an API key with
`sandbox:execute`. Demonstrates the real boundary: structured argv only,
workdir jail, capped output, normalized result.
"""

import os

from openagent.sandbox.client import SandboxClient

client = SandboxClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)

sb = client.create(profile="TEST", ttl_seconds=1800)
print("sandbox:", sb["sandbox_id"], sb["status"], sb["profile"])
client.start(sb["id"])

result = client.execute(sb["id"], ["pytest", "tests/", "-q"],
                        workdir="/workspace", timeout_seconds=600)
print("status:", result["status"], "exit:", result["exit_code"],
      "duration_ms:", result["duration_ms"])
print("risk:", result.get("risk_level"))
print("--- tail ---")
print(result.get("stdout_tail", "")[:2000])

assert result["status"] in ("SUCCEEDED", "FAILED", "TIMED_OUT"), result
client.destroy(sb["id"])
client.close()
