# OpenAgent Git Integration

Optional. Auto-sync is **OFF** by default and must be explicitly enabled per
project. OpenAgent never force-pushes, never deletes branches, and never
pushes when checks fail.

## Commands

```cmd
openagent git --init            # init repo + OpenAgent .gitignore
openagent git status            # read-only status
openagent git remote            # show origin (never changes it)
openagent git connect <url> [--force]   # set origin; refuses overwrite unless --force
openagent git auth              # check gh / SSH / credential-manager auth, guided hints
openagent git enable-auto-sync  # opt in (stored in .openagent/config.json)
openagent git sync [--message M]# scan -> commit actual changes -> push (no --force)
```

`git sync` flow: verify repo → secret-scan the tree (**blocked on
`Potential secret detected. Push blocked.`**) → `git status` → `git add -A` →
commit with a message generated from the actual changed files →
`git push` (plain, never `--force`). Empty tree reports clean and stops.

## Safety

- Never committed: `.env`, `.env.local`, API keys, passwords, tokens, private
  keys, database files, local models, caches, browser profiles, user secrets.
  `git --init` writes these rules to `.gitignore` automatically.
- Every sync runs the secret scanner first; a finding stops the push and
  prints the offending file/line (values redacted).
- Never hardcode tokens; use GitHub CLI (`gh auth login`), SSH, Git Credential
  Manager, or PAT. Tokens are never stored in project source.
- The gate fails closed by design: generated/cache directories are skipped,
  but intentional secret-like fixtures (e.g. fake keys inside security tests)
  still trip the scanner. Keep such fixtures out of auto-synced projects, or
  push manually after review — the block message names the exact file/line.
