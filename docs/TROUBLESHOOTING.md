# OpenAgent Troubleshooting

Start with `openagent doctor` (human-readable ✓/!/✗ + fixes) and
`openagent doctor --fix` for automatic PATH repair. Repo-level checks:
`node scripts/doctor.mjs`. Logs: `%LOCALAPPDATA%\OpenAgent\data\logs`
(`openagent logs --tail`).

## `openagent` not found after install

1. Restart your terminal (PATH updates apply to new shells).
2. Run `where openagent` — installer/MStore/clean installs provide
   `%LOCALAPPDATA%\OpenAgent\bin\openagent.cmd`; npm dev installs provide
   `<npm-prefix>\openagent.cmd`.
3. Run `openagent doctor --fix` to re-add the npm global bin to your user PATH.
4. If you ran `npm install -g openagent`: wrong package — that bare name is
   an unrelated registry placeholder. Use `npm install -g @openagent/cli`.

## Setup failed halfway

- Read the `SETUP FAILED / Reason:` block — it names the failing step.
- Run `openagent repair` (fixes dirs, cache, stale pid, corrupt config;
  never deletes workflows), then re-run setup.
- Offline? Use `openagent setup --offline --skip-model`, or the portable zip.
- Network errors (npm/GitHub/model/browser downloads): retry; downloads are
  versioned `OpenAgent-vX.Y.Z-win-x64.zip` artifacts with SHA256 verification,
  never `curl | bash`.

## Engine won't start / port busy

- `openagent status` shows pid/port/health; `openagent doctor` flags the port.
- Ports roll forward automatically (5678 → 5679 → …) and persist to config.
- Stuck process: `openagent stop`, then `openagent start --no-open`.

## AI / browser

- `openagent model doctor`: Ollama missing → install from https://ollama.com,
  then `openagent model install`. Cloud: set `OPENAI_API_KEY`.
- `openagent browser doctor` / `openagent browser install` manage the
  Playwright Chromium engine (no manual setup).

## Git push blocked

- `Potential secret detected. Push blocked.` → remove the secret, keep it in
  `.env` (gitignored), recommit.
- Push auth failure → `openagent git auth`, then `gh auth login` or SSH setup.

More: [getting-started/troubleshooting](getting-started/troubleshooting.md).
