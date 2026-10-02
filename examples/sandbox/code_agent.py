"""Sandbox code-agent: Code Agent tests now execute container-isolated.

Creates a coding task; `run_tests` flows Code Agent -> Tool Runtime ->
Sandbox (Docker) instead of the legacy host runner. Asserts the legacy
host path is gone in production by checking the security posture.
"""

import os

from openagent.code.client import CodeClient
from openagent.sandbox.client import SandboxClient

ORG = os.environ["OPENAGENT_ORG_ID"]
BASE = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000")
KEY = os.environ.get("OPENAGENT_API_KEY")

sbx = SandboxClient(base_url=BASE, api_key=KEY, organization_id=ORG)
check = sbx.security_check()
print("mode:", check.get("mode"), "ok:", check.get("ok"))
assert check.get("ok"), check

code = CodeClient(base_url=BASE, api_key=KEY, organization_id=ORG)
task = code.create_task(
    repository_id=os.environ["OPENAGENT_REPOSITORY_ID"],
    objective="Run the authentication test suite and report failures",
    max_steps=20,
)
print("task:", task["task_id"])
final = code.wait(task["id"], timeout_s=1800.0)
print("final:", final["status"])
print(code.task_diff(task["id"]))
sbx.close()
code.close()
