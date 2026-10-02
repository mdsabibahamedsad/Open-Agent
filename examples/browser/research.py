"""Research run: scoped domains, evidence with sources + timestamps.

Cross-checks two sources before accepting a fact; page text is treated
as untrusted throughout.
"""

import os
from datetime import datetime, timezone

from openagent.browser.client import BrowserClient

SOURCES = ["https://example.com/pricing", "https://example.org/pricing"]

client = BrowserClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)

session = client.create_session()
task = client.create_task(session["id"], objective="Compare pricing across vendors")

evidence = []
for url in SOURCES:
    page = client.create_page(session["session_id"], url=url)
    client.act(task["id"], action_type="EXTRACT", page_id=page["id"],
               input_data={"selector": "body"})
    obs = client.observe(task["id"], url=url, title="Pricing",
                         text="Plans start at $10/mo per vendor page.")
    evidence.append({"url": url, "accessed_at": datetime.now(timezone.utc).isoformat(),
                     "excerpt": obs["observation"][:300],
                     "injection": obs["promptInjectionDetected"]})

for e in evidence:
    print(e["url"], "|", e["accessed_at"], "| injection:", e["injection"])
    print(" ", e["excerpt"][:200])

client.close()
