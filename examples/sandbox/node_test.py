"""Sandbox node-test: npm test under the TEST profile, artifact export."""

import os

from openagent.sandbox.client import SandboxClient

client = SandboxClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)

sb = client.create(profile="TEST")
client.start(sb["id"])

result = client.execute(
    sb["id"], ["npm", "test", "--", "--reporter=json"],
    workdir="/workspace",
    artifacts=[{"path": "/workspace/test-results.json", "name": "results.json"}],
    timeout_seconds=900,
)
print("status:", result["status"], "exit:", result["exit_code"])
for art in result.get("artifacts", []):
    print("artifact:", art["name"], art["ref"], art.get("size_bytes"))

stored = client.artifacts(sb["id"])
print(f"stored artifacts: {len(stored)}")
client.destroy(sb["id"])
client.close()
