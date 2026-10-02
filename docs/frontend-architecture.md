# Frontend Architecture

Next.js 14 (App Router) + React 18 + TypeScript + Tailwind + TanStack Query.

## Routing

- `app/page.tsx` — Dashboard (protected)
- `app/(auth)/login|register|forgot-password|reset-password|verify-email` — public
- `app/agents|workflows|runs|tools|integrations|memory|marketplace|settings|account|platform|templates|docs` — protected app pages
- `components/protected.tsx` — client-side auth guard (backend remains authoritative)
- `src/middleware.ts` — security headers + CSP; session verification stays server-side in the API

## State

| Concern | Solution |
|---|---|
| Server state | TanStack Query via `lib/query-provider.tsx`; fetchers in `lib/queries.ts` (`useOrgScopedList`) |
| Session | `context/AuthContext.tsx` — single source of truth (`status/user/isLoading/error`) |
| Organization | `context/OrganizationContext.tsx` — org list, current org (localStorage `oa:org-id`), `X-Organization-ID` header |
| Permissions | `lib/permissions.ts` (`usePermission`, `useCan`) + `components/PermissionGate.tsx`; deny-by-default, platform owner bypass |
| Feature flags | `lib/feature-flags.tsx` + `NEXT_PUBLIC_FF_*` env |
| UI state | `hooks/hooks.ts` (`useLocalStorage` for sidebar), local component state, URL `?tab=` for settings |
| Toasts | `components/ui/toast.tsx` (`ToastProvider`, `useToast`) |
| Forms | Controlled inputs + `components/ui/form.tsx` (`Field`, `Switch`, `Checkbox`); Zod + React Hook Form where schemas exist |

## API client

`lib/api.ts` — typed `api.get/post/put/patch/delete`:

- `credentials: 'include'` (secure cookie sessions, no token in localStorage)
- `X-Request-ID` per request, `X-Organization-ID` from current org, optional `Idempotency-Key`
- JSON error parsing → `ApiError` with `kind` (`VALIDATION_ERROR|UNAUTHORIZED|FORBIDDEN|NOT_FOUND|CONFLICT|RATE_LIMITED|SERVER_ERROR|NETWORK_ERROR`)
- `toUserMessage()` maps to safe user-facing strings
- GET retry ×1, 30s timeout with AbortController, `signal` passthrough for cancellation

## App shell

`components/layout.tsx` (`AppShell`):

- Fixed sidebar (`components/sidebar.tsx`, collapsible → `oa:sidebar-collapsed`, `⌘/Ctrl+B`), mobile drawer
- Top bar (`components/top-nav.tsx`): org switcher, `⌘/Ctrl+K` search trigger, theme toggle, notifications, user menu
- `components/command-palette.tsx` — fuzzy-ish command list (pages, orgs, theme)
- `components/org-switcher.tsx`, `components/user-menu.tsx`, `components/notifications.tsx`
- Skip link, `<main id="main-content">`, error boundary per page

## Adding a feature

1. Add route under `app/<feature>/page.tsx` wrapped in `<Protected><Layout>`.
2. Add nav entry in `components/sidebar.tsx` (gate with `useFeature` if needed).
3. Add queries in `lib/queries.ts` via `useOrgScopedList` with real backend paths.
4. Gate actions with `<PermissionGate permission="resource:action">`.
5. Cover loading/empty/error with `DataTable` + `states.tsx`.
6. Add palette commands in `components/command-palette.tsx`.
