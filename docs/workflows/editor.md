# Workflow Editor

Route: `/workflows/[id]/edit` behind the `workflow_builder` flag.
Permissions: `workflow:create` (new/duplicate/import), `workflow:update`
(edit/save/publish/validate/restore), `workflow:delete`, `workflow:execute`
(Run button, honestly 501 until MP08), `execution:read` (run history).

## Module map

```
app/workflows/
  page.tsx            list + create dialog + duplicate/delete
  new/page.tsx        template gallery → create → builder
  [id]/page.tsx       detail: overview / versions (+restore) / runs / preview
  [id]/edit/page.tsx  builder shell: toolbar + grid + save states + conflict

features/workflows/
  types.ts            contract types (WorkflowNodeType, ports, Clipboard…)
  node-catalog.ts     registry: categories, versions, ports, register API
  schema.ts           zod shape gate for imports
  validate.ts         synchronous client validation (mirrors backend)
  expressions.ts      {{...}} detection, reference checks, suggestions
  serialize.ts        ids, import/export envelope, migration gate, templates
  use-workflow-editor.ts  reducer: selection/multi-select, undo/redo,
                          copy/paste/duplicate, dirty, autosave
  workflows-api.ts    React Query hooks for every backend endpoint

components/workflows/
  WorkflowCanvas.tsx  SVG canvas (pan/zoom/box-select/ports/context menu)
  WorkflowMinimap.tsx viewport minimap with click/drag navigation
  CanvasContextMenu.tsx Configure/Duplicate/Copy/Disable/Note/Delete…
  NodePalette.tsx     search + category filter + recent + favorites
  Inspector.tsx       trigger/node/edge forms, notes, disable, variables
  ValidationPanel.tsx local results + server dry-run + click-to-select
  History.tsx         VersionHistory (preview + restore) + RunHistory
  CreateWorkflowDialog.tsx
```

## State separation (§37)

- **Server state**: React Query (`workflows-api.ts`) — workflow, versions,
  executions. Never duplicated into editor state.
- **Editor state**: `useWorkflowEditor` — definition, selection +
  `selectedIds`, undo/redo stacks, clipboard, pending edge, dirty baseline.
- **UI state**: viewport/palette search/box rect/context menu (canvas-local),
  toolbar save status (page-local), drawers/dialogs.

## Canvas interactions

| Gesture | Action |
|---|---|
| Background drag | Pan |
| Shift+drag | Box select (nodes + triggers) |
| Wheel | Zoom to cursor (non-passive listener) |
| Ctrl/Cmd+click | Toggle multi-select |
| Right-click | Context menu |
| Output port → input port | Connect (duplicate pairs rejected) |
| Del/Backspace | Delete selection |
| Ctrl+C / V / D | Copy / paste / duplicate (fresh ids, +48px offset) |
| Ctrl+S | Save (page-level, works from anywhere) |
| Ctrl+Z / Ctrl+Y | Undo / redo (drags commit one entry) |
| Arrows / Shift+arrows | Nudge selection 4px / 16px |
| F | Fit to view |
| Esc | Cancel connection / clear selection / close menu |

Every canvas operation has a non-canvas path: palette adds, inspector
deletes/configures, toolbar undoes/saves.

## Save system (§25)

States: `Saved ✓` · `● Unsaved changes` · `Saving…` · `Save failed + Retry` ·
`Offline — kept locally`. Autosave drafts go to
`localStorage[oa:wf-draft:<id>]` (debounced); a restore banner appears when
the draft differs from the saved version; `beforeunload` guards navigation.
Conflicting saves (HTTP 409 on `expected_updated_at`) open a dialog:
Reload server version / Keep local draft — newer server state is never
silently overwritten.

## Responsive / accessibility (§34–35)

Desktop-first grid collapses gracefully (`lg:` palette hide, stacked panels).
Skip the canvas on small screens is *not* done — instead panels stack below
it. Canvas: `role=application` with instructions, focusable nodes
(Enter/Space selects), visible focus rings, `prefers-reduced-motion`
inherited from the shell, status changes via `role=status`/`alert` toasts and
`aria-live` save/validation indicators. Validation issues are buttons that
move selection to the offending node.
