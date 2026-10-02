"""Structured extraction + observation labeling.

Page text is untrusted: the server wraps injection hits as
[UNTRUSTED_WEB_CONTENT] and reports signals alongside the observation.
"""

import os

from openagent.browser.client import BrowserClient

client = BrowserClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)

session = client.create_session()
page = client.create_page(session["session_id"], url="https://example.com/pricing")
task = client.create_task(session["id"], objective="Extract pricing table")

print(client.act(task["id"], action_type="EXTRACT", page_id=page["id"],
                 input_data={"selector": "table.pricing", "multiple": True}))

obs = client.observe(task["id"], url="https://example.com/pricing",
                     title="Pricing", text="Plans start at $10/mo.")
print("injection:", obs["promptInjectionDetected"], "| challenge:", obs["challenge"])
print(obs["observation"][:500])

client.close()
