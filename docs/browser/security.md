# Browser Security

Fail-closed, layered defense. When verification is impossible, OpenAgent
refuses.

## Navigation gates (`validate_url`)

- Allowed schemes: `http`, `https` only. Blocked: `file`, `ftp`,
  `javascript`, `data`, `blob`, `chrome`, `devtools`, extensions, …
- Blocked hosts: `localhost`, loopback, `0.0.0.0`.
- Blocked networks: private/loopback/link-local/reserved/multicast ranges
  (IPv4 + IPv6), numeric/obfuscated hosts.
- Cloud metadata endpoints blocked (`169.254.169.254`,
  `metadata.google.internal`, `metadata.azure.com`, …).
- No userinfo (`user:pass@host`), no control characters, unsafe ports
  (22, 5432, 6379, …) blocked.
- Redirects revalidated (`validate_redirect`).

## Domain policies

`ALLOW | DENY | CONFIRM` at platform → organization → team → user → agent →
workflow → profile → task scope; most-specific domain + priority wins.
`CONFIRM` requires explicit approval before navigation.

## Trust boundary

```text
System Policy > OpenAgent Policy > Agent Instructions > User Task
  > Tool Results > Web Content (UNTRUSTED, never instructs)
```

`detect_prompt_injection` scans page text for override/exfiltration/destruction
patterns; hits are labeled, redacted, and surfaced — never executed.

## Data protection

`redact_text`/`redact_dict` scrub passwords, tokens, API keys, cookies and
payment data before logs, telemetry, model context, task history and errors.
Raw secrets are rejected at the credential boundary: the model only ever sees
`credential_ref` handles.

## Challenges

CAPTCHA / MFA / login / bot-challenge detection parks the task in
`WAITING_FOR_HUMAN`. **No CAPTCHA or challenge bypass exists by design.**

## Uploads/downloads

Extension + MIME + size gates, tenant-isolated storage, filename
sanitization, malware-scan hook point, audit events. Host filesystem paths
are never exposed to the model.
