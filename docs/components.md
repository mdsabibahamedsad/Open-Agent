# Components

Conventions:

- Client components start with `'use client'`.
- Shared primitives live in `components/ui/`; shell in `components/`; guards in `components/protected.tsx`, `components/PermissionGate.tsx`, `components/error-boundary.tsx`.
- Never hard-code colors — use semantic classes (`bg-card`, `text-muted-foreground`, `StatusBadge`).
- Every async view: `loading` (skeleton) → `error` (ErrorState + retry + request ID) → `empty` (EmptyState with what/why/next) → `data`.
- Destructive actions use `ConfirmDialog`; extremely destructive ones pass `requireText`.
- Dialogs trap focus (initial focus), close on Esc, set `role="dialog" aria-modal`.
- Tables: `DataTable` with `Column<T>` (`key/header/render/accessor/sortable`); paginate only when backend returns totals.
- Toasts for transient feedback only (`useToast().toast({kind,title,description})`); errors surface `toUserMessage`.
- `PermissionGate` hides/disables UI only — backend enforces.
