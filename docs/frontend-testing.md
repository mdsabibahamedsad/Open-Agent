# Frontend Testing

- Unit/component: `vitest` + Testing Library + jsdom (`vitest.config.mjs`, `vitest.setup.mjs`).
  - `src/components/ui/button.test.tsx` (existing), `src/lib/api.test.ts` (error mapping),
    `src/components/ui/states.test.tsx`, `src/lib/permissions.test.ts`.
  - Run: `pnpm --filter @openagent/web test` (or `npm run test` in `apps/web`).
- Auth/org/permission: component tests render guards with mocked contexts
  (unauthenticated → redirect copy; forbidden → `PermissionGate` fallback).
- API states: `DataTable` loading/error/empty covered; `toUserMessage` maps 400/401/403/404/409/429/500/network.
- E2E (Playwright, recommended): login → dashboard → org switch → settings → member list → agents/workflows list → logout,
  against a test backend; never production.ാത്ത്Wire as `test:e2e` when Playwright is added.
- Accessibility: `axe-core` pass on shell + dashboard + settings; keyboard-only run of palette/dialog/drawer.
