"""Basic navigation: session -> page -> gated NAVIGATE action.

Uses only the canonical API (policy-aware). Requires a running API
(`docker compose up`) and an API key with browser access.
"""

import os

from openagent.browser.client import BrowserClient

client = BrowserClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)

session = client.create_session(headless=True)
print("session:", session["session_id"], session["status"])

page = client.create_page(session["session_id"], url="https://example.com")
print("page:", page["page_id"], page["url"])

task = client.create_task(session["id"], objective="Open example.com and confirm it loaded")
print("task:", task["task_id"], task["status"])

result = client.act(task["id"], action_type="NAVIGATE", page_id=page["id"],
                    input_data={"url": "https://example.com"})
print("navigate:", result)

client.close()
