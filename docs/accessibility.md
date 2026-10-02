# Accessibility

Target: WCAG 2.2 AA where practical.

- Semantic landmarks: `banner`, `main#main-content`, `nav` (primary/secondary/breadcrumb), `dialog`, `listbox/option`, `status/alert`.
- Skip link to `#main-content`.
- Visible `:focus-visible` ring everywhere; icon-only buttons always have `aria-label`.
- Dialogs: `role=dialog aria-modal`, Esc to close, initial focus; drawers same.
- Palette: `combobox/listbox/option` with `aria-activedescendant`.
- Tables use `scope="col"`; sort buttons expose `aria-label`.
- Status never color-only (`StatusBadge` dot + text).
- `prefers-reduced-motion` disables transitions.
- Contrast: muted text ≥4.5:1 tuned in both themes.
- Automated checks: `axe-core` recommended in E2E (`test:e2e`); unit tests assert labels/roles.
