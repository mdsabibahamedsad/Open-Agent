"""Code review: independent structured review of a task diff or raw text."""

import os

from openagent.code.client import CodeClient

client = CodeClient(
    base_url=os.environ.get("OPENAGENT_API_URL", "http://localhost:8000"),
    api_key=os.environ.get("OPENAGENT_API_KEY"),
    organization_id=os.environ["OPENAGENT_ORG_ID"],
)

task_id = os.environ.get("OPENAGENT_TASK_ID")
if task_id:
    review = client.review_task(task_id)
else:
    review = client.review_text(
        "src/auth.py",
        "def validate_session(token):\n"
        "    import os\n"
        "    print(os.environ)\n"
        "    return token is not None\n",
    )

print("review:", review.get("status"))
for f in review.get("findings", []):
    print(f"[{f['severity']}] {f.get('category')} "
          f"{f.get('file', '')}:{f.get('line', '')} — {f['finding'][:160]}")
    if f.get("suggested_fix"):
        print("  fix:", f["suggested_fix"][:160])

client.close()
