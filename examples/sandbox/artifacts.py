"""Sandbox artifacts: explicit export, storage refs, no container paths."""

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
    sb["id"], ["pytest", "--junitxml=/workspace/report.xml", "-q"],
    workdir="/workspace",
    artifacts=[{"path": "/workspace/report.xml", "name": "junit.xml"}],
)
print("status:", result["status"])
for art in result.get("artifacts", []):
    assert not art["ref"].startswith("/"), "container path leaked!"
    print("artifact ref:", art["ref"])

events = client.events(sb["id"])
print("events:", [(e["type"]) for e in events[:8]])
client.destroy(sb["id"])
client.close()
