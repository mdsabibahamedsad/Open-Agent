# Contributing (Developer Pointer)

The canonical contribution guide is [`CONTRIBUTING.md`](../../CONTRIBUTING.md) at the repository root. Follow it; the summary below is not a replacement.

1. Fork, branch, implement with tests.
2. Run before opening a PR:
   - `pnpm lint`
   - `pnpm typecheck`
   - `pnpm test`
   - `pnpm doctor`
3. Open a PR with the template in `.github/PULL_REQUEST_TEMPLATE.md`.

Extension authors: start at [`docs/developers/`](../developers/) and the [security guide](../developers/security.md). Never commit `.env`, credentials, or private keys — see [environment guide](../getting-started/environment.md).
