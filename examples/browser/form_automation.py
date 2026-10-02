"""Form automation with credential references (never raw secrets).

The model/server only ever sees ``credential_ref`` handles; resolution
happens server-side in the credential system.
"""

import os

from openagent.browser.client import BrowserClient

client = BrowserClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)

session = client.create_session()
page = client.create_page(session["session_id"], url="https://example.com/login")
task = client.create_task(session["id"], objective="Fill the login form using stored credentials")

# Fill uses a credential REFERENCE — raw values never cross this boundary.
print(client.act(task["id"], action_type="FILL", page_id=page["id"],
                 input_data={"selector": "#email", "credential_ref": "login_email"}))
print(client.act(task["id"], action_type="CLICK", page_id=page["id"],
                 input_data={"selector": "button[type=submit]"}))

client.close()
