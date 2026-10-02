"""Sandbox build: BUILD profile, no network, build-output artifact."""

import os

from openagent.sandbox.client import SandboxClient

client = SandboxClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)

sb = client.create(profile="BUILD", ttl_seconds=1800)
client.start(sb["id"])

result = client.execute(
    sb["id"], ["npm", "run", "build"],
    workdir="/workspace",
    artifacts=[{"path": "/workspace/dist/bundle.js", "name": "bundle.js"}],
    timeout_seconds=1200,
)
print("status:", result["status"], "exit:", result["exit_code"],
      "peak_mb:", result.get("peak_memory_mb"))
assert result["status"] in ("SUCCEEDED", "FAILED"), result
client.destroy(sb["id"])
client.close()
