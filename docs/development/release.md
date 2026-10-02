# Release

How we cut a safe release. See [`CHANGELOG.md`](../../CHANGELOG.md) for history and [`SECURITY.md`](../../SECURITY.md) for disclosure.

## Pre-release checklist

```bash
git status
git diff
git diff --cached
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm doctor
```

Do not hide unrelated existing failures — report them as `Existing failure` vs `New failure` vs `Fixed failure`.

## Secret safety

```bash
git ls-files | grep -E '(^|/)\.env($|\.)' | grep -v '\.env\.example$'
```

The command must print nothing (only `.env.example` is ever tracked). Never commit `.env`, credentials, private keys, or local databases. CI also enforces this (`security.yml` → "No env files tracked") plus Gitleaks.

## Versioning

- `CHANGELOG.md` entry for every user-visible change.
- Tag from `main` only after CI (`ci.yml`: lint, typecheck, backend/frontend/worker tests, security gates, package tests, Docker builds) is green.
- Never force-push (`git push --force` is forbidden); never rewrite published history.

## Push

```bash
git branch -M main
git push -u origin main
git status
git log -1 --oneline
git ls-remote origin
```
