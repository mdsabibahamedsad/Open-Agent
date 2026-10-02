# Browser Deployment

## Chromium dependencies

The API container does **not** need a browser. Real page driving happens in
browser workers / uplink processes with Playwright + Chromium:

```bash
# Node uplink (packages/browser provider)
pnpm --filter @openagent/browser exec playwright install --with-deps chromium
```

`--with-deps` installs OS libraries (libnss3, libatk, libxkbcommon, …).
Without them Chromium fails to launch — the provider surfaces a clear
`Playwright is not installed` / launch error, and tasks stay `QUEUED`.

Python API containers need no extra packages (`httpx` is already declared).

## Sizing (per browser worker)

| Resource | Development | Production worker |
|---|---|---|
| CPU | 2 | 4+ (Chromium is process-heavy) |
| Memory | 4 GB | 8 GB+ (`max browsers` × ~300–500 MB) |
| Disk | 2 GB (browser + downloads) | 20 GB+ (artifacts, HAR/video when enabled) |

## Concurrency & limits (env-configurable)

```text
BROWSER_MAX_SESSIONS_ORG=50        BROWSER_MAX_SESSIONS_USER=10
BROWSER_MAX_PAGES_SESSION=20       BROWSER_SESSION_TIMEOUT_MIN=30
BROWSER_IDLE_TIMEOUT_MIN=5         BROWSER_MAX_STEPS=100 (≤500 hard cap)
BROWSER_MAX_DOWNLOAD_MB=100        BROWSER_MAX_UPLOAD_MB=25
```

Never trade tenant isolation for throughput: no context/cookie sharing
across organizations, even via pooling.

## Networking

Egress-allowlist where possible; the in-app SSRF gates (private IPs,
metadata endpoints, unsafe schemes/ports) are a second layer, not the only
one. Run browser workers in a dedicated subnet/namespace without routes to
internal services. Proxy injection happens only through approved
infrastructure (`provider.proxy`).

## Scaling path

`single-node → Docker → Kubernetes → cloud browser workers → remote
providers` via the provider-neutral `BrowserProvider` interface
(`playwright` today; `browserless` / `remote-chromium` / `cloud-browser`
later). The full execution sandbox arrives in MP18; until then treat every
page as hostile (it is labeled untrusted end-to-end).

## Observability

Events (`browser.session.*`, `browser.action.*`, `browser.challenge.*`,
`browser.human_required`, …), metrics (`browser_*`), redacted logs, and
audit entries (`browser.session.*`, `browser.policy.*`, `browser.profile.*`)
flow through the existing pipelines — no parallel observability stack.
