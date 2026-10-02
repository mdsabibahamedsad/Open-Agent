# Design System

Semantic tokens in `apps/web/src/app/globals.css` (`:root` / `.dark`), consumed via Tailwind
(`tailwind.config.js` maps `primary/success/warning/info/card/popover/sidebar` to `hsl(var(--…))`).

## Tokens

Colors: `background, foreground, card, popover, primary, secondary, muted, accent,
destructive, success, warning, info, border, input, ring, sidebar`.
Also: `--radius`, shadows, `--z-dropdown/modal/drawer/toast/command`, transitions.
Typography utilities: `.oa-display .oa-h1 .oa-h2 .oa-h3 .oa-body .oa-small .oa-caption .oa-code`.
Layout: `.oa-surface .oa-page .oa-page-header`.

## Themes

`next-themes` (`class` mode, `system` default, `disableTransitionOnChange`).
Dark and light palettes are separately designed (layered surfaces, ≥4.5:1 body contrast).
No theme flash: `suppressHydrationWarning` + class strategy.

## Components (`components/ui/`)

Button, Input, Textarea/Select/Switch/Checkbox/Field (`form.tsx`), Label, Badge,
Avatar, Card, Tabs, Separator, DropdownMenu, Dialog (+ConfirmDialog), Drawer,
Toast (`ToastProvider/useToast`), Table (`DataTable` with sort/pagination/loading/empty/error),
`loading.tsx` (Skeleton/Spinner/PageLoading/TableSkeleton), `states.tsx` (EmptyState/ErrorState),
`status.tsx` (`StatusBadge` — never color-only: dot + text label), `page.tsx`
(Breadcrumbs/PageHeader), Alert.

Icons: `lucide-react` only. Motion: `animate-fade-in` only; `prefers-reduced-motion` disables animation.
