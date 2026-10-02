"""Download flow: gated action, isolated storage, audit trail.

Size/MIME/filename gates run server-side; the client only receives a
storage reference — never a host path.
"""

import os

from openagent.browser.client import BrowserClient

client = BrowserClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)

session = client.create_session()
page = client.create_page(session["session_id"], url="https://example.com/report")
task = client.create_task(session["id"], objective="Download the monthly report")

result = client.act(task["id"], action_type="DOWNLOAD", page_id=page["id"],
                    input_data={"selector": "a#report-pdf", "idempotencyKey": "report-2026-09"})
print(result)

client.close()
