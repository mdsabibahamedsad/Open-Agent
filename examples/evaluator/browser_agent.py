"""Example — Browser agent: act -> observe -> verify state -> correct.

Click Submit -> wait -> verify URL/DOM/success indicator -> uncertain ->
additional verification -> failed -> correction -> final result.

Requires a running API and env:
  OPENAGENT_API_URL, OPENAGENT_API_KEY, OPENAGENT_ORG_ID, OPENAGENT_BROWSER_TASK_ID
"""

import json
import os
import urllib.request

BASE = os.environ.get("OPENAGENT_API_URL", "http://localhost:8000")
ORG = os.environ["OPENAGENT_ORG_ID"]
KEY = os.environ.get("OPENAGENT_API_KEY", "")
TASK = os.environ["OPENAGENT_BROWSER_TASK_ID"]


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


# Observed page state after the click (from the browser worker/observation).
observed = {"url": "https://shop.example/checkout/success",
            "title": "Order confirmed",
            "dom": "<h1>Thank you</h1><span id='order-id'>ORD-123</span>",
            "has_selector": True, "challenge": None}

outcome = call("POST", f"/api/v1/browser/tasks/{TASK}/verify", {
    "observed": observed,
    "expectations": {"expected_url_contains": "/success",
                     "required_selector": "#order-id",
                     "success_text": "Thank you",
                     "forbid_challenge": True},
})
print("browser decision:", outcome["decision"], outcome["score"])
# 'Button clicked' alone would never pass: URL/DOM/success are all checked.
assert outcome["decision"] == "PASS"
