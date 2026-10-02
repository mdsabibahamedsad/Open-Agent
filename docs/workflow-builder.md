# Visual Workflow Builder

Route: `/workflows/[id]/edit`. Behind the `workflow_builder` feature flag
(default on). Permissions: `workflow:create` (new/duplicate),
`workflow:update` (edit/save/publish/validate), `workflow:delete`,
`workflow:execute` (Run button), `execution:read` (run history).

## Architecture

```
app/workflows/
  page.tsx            list + create dialog + duplicate/delete
  new/page.tsx        template gallery -> create -> builder
  [id]/page.tsx       detail (overview / versions / runs / graph preview)
  [id]/edit/page.tsx  builder shell (toolbar + grid)

features/workflows/
  types.ts            definition contract + API shapes
  schema.ts           zod shape-check for imports
  node-catalog.ts     palette metadata (icons, ports, fields, defaults)
  validate.ts         synchronous client validation (mirrors backend)
  serialize.ts        import/export, id factories, built-in templates
  use-workflow-editor.ts   reducer + undo/redo + dirty + autosave
  workflows-api.ts    React Query hooks for every backend endpoint

components/workflows/
  WorkflowCanvas.tsx  custom SVG canvas (no graph dependency)
  NodePalette.tsx     search + click-to-add + drag-to-canvas
  Inspector.tsx       trigger/node/edge forms + workflow variables/settings
  ValidationPanel.tsx local results + server dry-run + click-to-select
  History.tsx         VersionHistory + RunHistory tables
  CreateWorkflowDialog.tsx
```

## Canvas interactions

- Background drag = pan; wheel = zoom to cursor; controls = zoom/fit/%.
- Node drag with 4px snap; a single undo entry is committed per gesture
  (`move-item` is history-free, `commit-move` snapshots on pointer-up).
- Edge creation: drag an output port onto an input port. Duplicate pairs are
  rejected. Esc cancels; clicking the background clears selection.
- Keyboard (canvas focused, not typing): `Delete` removes selection,
  `Ctrl+Z`/`Ctrl+Y` undo/redo, arrows nudge (Shift = 16px), `Enter`/`Space`
  on a focused node selects it. Every canvas operation also exists outside
  the canvas: palette + buttons add, inspector deletes.
- Read-only mode (`readOnly`) reuses the same renderer for the detail-page
  graph preview with all mutation affordances removed.

## Save / versions / publish

- Save (`PATCH definition`) snapshots a new draft version (`vN+1`); the toast
  says so. Dirty state compares against the loaded baseline; autosave drafts
  go to `localStorage` (`oa:wf-draft:<id>`, debounced) and a restore banner
  appears when the draft differs from the saved version.
- Publish requires a clean local validation pass, then the server re-validates
  (422 surfaces field-level errors). `beforeunload` guards unsaved work.
- Import validates shape via zod before entering the editor; export downloads
  the exact versioned JSON the server stores.

## Runs (honest stub)

The detail and builder Run buttons call `POST .../execute`, which returns
501 (`EXECUTION_ENGINE_NOT_IMPLEMENTED`) until the execution engine lands.
The UI toasts this explicitly — runs are never faked. `RunHistory` reads the
real executions endpoint (empty until the engine writes rows).

## Adding a node type

1. Extend `WorkflowNodeType` + catalog entry (ports, fields, defaults).
2. Add required-config rules to `validate.ts` **and** the backend validator.
3. The canvas renders any catalog type generically — no canvas change needed.
