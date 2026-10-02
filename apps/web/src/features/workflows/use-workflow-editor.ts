'use client';

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { validateWorkflowDefinition } from './validate';
import {
  makeEdge,
  makeNode,
  makeTrigger,
  newId,
  stripSensitive,
  stripSensitiveTrigger,
} from './serialize';
import type {
  Clipboard,
  TriggerType,
  ValidationResult,
  WorkflowDefinition,
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeType,
  WorkflowTrigger,
} from './types';

// Editor state: definition + selection + undo/redo + dirty + autosave.
// Canvas and inspector are both driven by this hook; nothing else mutates
// the definition.

export interface Selection {
  kind: 'trigger' | 'node' | 'edge';
  id: string;
}

interface EditorState {
  definition: WorkflowDefinition;
  selection: Selection | null;
  /** All selected ids (primary selection first). Drives multi-move/delete/copy. */
  selectedIds: string[];
  past: WorkflowDefinition[];
  future: WorkflowDefinition[];
}

type Action =
  | { type: 'load'; definition: WorkflowDefinition }
  | { type: 'add-trigger'; trigger: WorkflowTrigger }
  | { type: 'add-node'; node: WorkflowNode }
  | { type: 'move-item'; id: string; x: number; y: number }
  | { type: 'commit-move'; before: WorkflowDefinition }
  | { type: 'update-trigger'; id: string; patch: Partial<WorkflowTrigger> }
  | { type: 'update-node'; id: string; patch: Partial<WorkflowNode> }
  | { type: 'update-edge'; id: string; patch: Partial<WorkflowEdge> }
  | { type: 'add-edge'; edge: WorkflowEdge }
  | { type: 'delete-selection' }
  | { type: 'delete-ids'; ids: string[] }
  | { type: 'duplicate-items'; items: Clipboard }
  | { type: 'select'; selection: Selection | null }
  | { type: 'toggle-select'; selection: Selection }
  | { type: 'box-select'; ids: string[] }
  | { type: 'undo' }
  | { type: 'redo' };

const HISTORY_LIMIT = 60;

function kindOf(definition: WorkflowDefinition, id: string): Selection['kind'] | null {
  if (definition.triggers.some((t) => t.id === id)) return 'trigger';
  if (definition.nodes.some((n) => n.id === id)) return 'node';
  if (definition.edges.some((e) => e.id === id)) return 'edge';
  return null;
}

function pushHistory(state: EditorState, definition: WorkflowDefinition): EditorState {
  const past = [...state.past, state.definition].slice(-HISTORY_LIMIT);
  return { definition, selection: state.selection, selectedIds: state.selectedIds, past, future: [] };
}

/** Exported for unit tests (components should use `useWorkflowEditor`). */
export function createEditorState(definition: WorkflowDefinition): EditorState {
  return { definition, selection: null, selectedIds: [], past: [], future: [] };
}

/** Exported for unit tests. */
export const editorReducer = reducer;

function reducer(state: EditorState, action: Action): EditorState {  switch (action.type) {
    case 'load':
      return { definition: action.definition, selection: null, selectedIds: [], past: [], future: [] };
    case 'add-trigger':
      return pushHistory(state, {
        ...state.definition,
        triggers: [...state.definition.triggers, action.trigger],
      });
    case 'add-node':
      return pushHistory(state, {
        ...state.definition,
        nodes: [...state.definition.nodes, action.node],
      });
    case 'move-item': {
      // History-free: called per mousemove during a drag. The drag gesture
      // commits a single undo entry via 'commit-move' on pointer-up.
      const triggers = state.definition.triggers.map((t) =>
        t.id === action.id ? { ...t, position: { x: action.x, y: action.y } } : t,
      );
      const nodes = state.definition.nodes.map((item) =>
        item.id === action.id ? { ...item, position: { x: action.x, y: action.y } } : item,
      );
      return {
        ...state,
        definition: { ...state.definition, triggers, nodes },
      };
    }
    case 'commit-move': {
      if (JSON.stringify(action.before) === JSON.stringify(state.definition)) return state;
      return {
        ...state,
        past: [...state.past, action.before].slice(-HISTORY_LIMIT),
        future: [],
      };
    }
    case 'update-trigger':
      return pushHistory(state, {
        ...state.definition,
        triggers: state.definition.triggers.map((t) =>
          t.id === action.id ? { ...t, ...action.patch } : t,
        ),
      });
    case 'update-node':
      return pushHistory(state, {
        ...state.definition,
        nodes: state.definition.nodes.map((n) =>
          n.id === action.id ? { ...n, ...action.patch } : n,
        ),
      });
    case 'update-edge':
      return pushHistory(state, {
        ...state.definition,
        edges: state.definition.edges.map((e) =>
          e.id === action.id ? { ...e, ...action.patch } : e,
        ),
      });
    case 'add-edge': {
      const exists = state.definition.edges.some((e) => e.from === action.edge.from && e.to === action.edge.to);
      if (exists) return state;
      return pushHistory(state, {
        ...state.definition,
        edges: [...state.definition.edges, action.edge],
      });
    }
    case 'delete-selection': {
      const ids = state.selectedIds.length > 0
        ? state.selectedIds
        : state.selection
          ? [state.selection.id]
          : [];
      if (ids.length === 0) return state;
      return deleteIds(state, ids);
    }
    case 'delete-ids': {
      if (action.ids.length === 0) return state;
      return deleteIds(state, action.ids);
    }
    case 'duplicate-items': {
      return pushHistory(state, {
        ...state.definition,
        triggers: [...state.definition.triggers, ...action.items.triggers],
        nodes: [...state.definition.nodes, ...action.items.nodes],
        edges: [...state.definition.edges, ...action.items.edges],
      });
    }
    case 'select':
      return {
        ...state,
        selection: action.selection,
        selectedIds: action.selection ? [action.selection.id] : [],
      };
    case 'toggle-select': {
      const id = action.selection.id;
      if (state.selectedIds.includes(id)) {
        const rest = state.selectedIds.filter((x) => x !== id);
        const primary = rest.length > 0
          ? (state.selection?.id === id
              ? { kind: kindOf(state.definition, rest[0]) ?? 'node', id: rest[0] } as Selection
              : state.selection)
          : null;
        return { ...state, selection: primary, selectedIds: rest };
      }
      return { ...state, selection: action.selection, selectedIds: [...state.selectedIds, id] };
    }
    case 'box-select': {
      const ids = action.ids.filter((id) => kindOf(state.definition, id) !== null);
      if (ids.length === 0) return { ...state, selection: null, selectedIds: [] };
      const kind = kindOf(state.definition, ids[0]) ?? 'node';
      return { ...state, selection: { kind, id: ids[0] }, selectedIds: ids };
    }
    case 'undo': {
      if (state.past.length === 0) return state;
      const previous = state.past[state.past.length - 1];
      return {
        definition: previous,
        selection: state.selection,
        selectedIds: state.selectedIds,
        past: state.past.slice(0, -1),
        future: [state.definition, ...state.future].slice(0, HISTORY_LIMIT),
      };
    }
    case 'redo': {
      if (state.future.length === 0) return state;
      const [next, ...rest] = state.future;
      return {
        definition: next,
        selection: state.selection,
        selectedIds: state.selectedIds,
        past: [...state.past, state.definition].slice(-HISTORY_LIMIT),
        future: rest,
      };
    }
    default:
      return state;
  }
}

function deleteIds(state: EditorState, ids: string[]): EditorState {
  const idSet = new Set(ids);
  return pushHistory(
    {
      ...state,
      selection: null,
      selectedIds: [],
    },
    {
      ...state.definition,
      triggers: state.definition.triggers.filter((t) => !idSet.has(t.id)),
      nodes: state.definition.nodes.filter((n) => !idSet.has(n.id)),
      edges: state.definition.edges.filter(
        (e) => !idSet.has(e.id) && !idSet.has(e.from) && !idSet.has(e.to),
      ),
    },
  );
}

export interface PendingEdge {
  fromId: string;
  fromPort: string;
}

export function useWorkflowEditor(options: {
  initial: WorkflowDefinition;
  draftKey?: string;
  baseline?: WorkflowDefinition | null;
}) {
  const { initial, draftKey, baseline } = options;
  const [state, dispatch] = useReducer(reducer, {
    definition: initial,
    selection: null,
    selectedIds: [],
    past: [],
    future: [],
  });
  const [pendingEdge, setPendingEdge] = useState<PendingEdge | null>(null);
  const [restoredDraft, setRestoredDraft] = useState(false);
  const [clipboard, setClipboard] = useState<Clipboard | null>(null);
  const clipboardRef = useRef<Clipboard | null>(null);
  clipboardRef.current = clipboard;
  const baselineRef = useRef<string>('');
  const stateRef = useRef(state);
  stateRef.current = state;

  // Establish the saved baseline once (for dirty tracking).
  useEffect(() => {
    if (baseline) baselineRef.current = JSON.stringify(baseline);
  }, [baseline]);

  // Restore autosaved draft once.
  useEffect(() => {
    if (!draftKey || restoredDraft) return;
    try {
      const raw = window.localStorage.getItem(draftKey);
      if (raw) {
        const parsed = JSON.parse(raw) as WorkflowDefinition;
        if (parsed && parsed.schema_version === '1.0') {
          dispatch({ type: 'load', definition: parsed });
        }
      }
    } catch {
      // Corrupt draft — start from initial.
    } finally {
      setRestoredDraft(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey]);

  // Autosave (debounced).
  useEffect(() => {
    if (!draftKey || !restoredDraft) return;
    const t = setTimeout(() => {
      try {
        window.localStorage.setItem(draftKey, JSON.stringify(stateRef.current.definition));
      } catch {
        // Quota — ignore; explicit save still works.
      }
    }, 800);
    return () => clearTimeout(t);
  }, [state.definition, draftKey, restoredDraft]);

  const clearDraft = useCallback(() => {
    if (draftKey) {
      try {
        window.localStorage.removeItem(draftKey);
      } catch {
        /* noop */
      }
    }
  }, [draftKey]);

  const markSaved = useCallback((definition: WorkflowDefinition) => {
    baselineRef.current = JSON.stringify(definition);
    clearDraft();
  }, [clearDraft]);

  const dirty = useMemo(() => {
    if (!baselineRef.current) return state.past.length > 0;
    return JSON.stringify(state.definition) !== baselineRef.current;
  }, [state.definition, state.past.length]);

  const validation: ValidationResult = useMemo(
    () => validateWorkflowDefinition(state.definition),
    [state.definition],
  );

  const errorsFor = useCallback(
    (id: string) => validation.errors.filter((e) => e.node_id === id),
    [validation],
  );

  // Mutators -------------------------------------------------------------
  const addTrigger = useCallback((type: TriggerType, at?: { x: number; y: number }) => {
    const trigger = { ...makeTrigger(type, at), position: at ?? { x: 80, y: 80 } };
    dispatch({ type: 'add-trigger', trigger });
    dispatch({ type: 'select', selection: { kind: 'trigger', id: trigger.id } });
    return trigger.id;
  }, []);

  const addNode = useCallback((type: WorkflowNodeType, at?: { x: number; y: number }) => {
    const node = makeNode(type, at);
    dispatch({ type: 'add-node', node });
    dispatch({ type: 'select', selection: { kind: 'node', id: node.id } });
    return node.id;
  }, []);

  const connect = useCallback((fromId: string, toId: string, port = 'out') => {
    if (fromId === toId) return false;
    const already = stateRef.current.definition.edges.some((e) => e.from === fromId && e.to === toId);
    if (already) return false;
    dispatch({ type: 'add-edge', edge: makeEdge(fromId, toId, port) });
    return true;
  }, []);

  const select = useCallback((selection: Selection | null) => dispatch({ type: 'select', selection }), []);

  const toggleSelect = useCallback(
    (selection: Selection) => dispatch({ type: 'toggle-select', selection }),
    [],
  );

  const boxSelect = useCallback((ids: string[]) => dispatch({ type: 'box-select', ids }), []);

  /** Snapshot current selection into the clipboard (sensitive values stripped). */
  const copySelection = useCallback((): boolean => {
    const def = stateRef.current.definition;
    const ids = stateRef.current.selectedIds;
    if (ids.length === 0) return false;
    const idSet = new Set(ids);
    setClipboard({
      triggers: def.triggers.filter((t) => idSet.has(t.id)).map(stripSensitiveTrigger),
      nodes: def.nodes.filter((n) => idSet.has(n.id)).map(stripSensitive),
      edges: def.edges.filter((e) => idSet.has(e.from) && idSet.has(e.to)),
    });
    return true;
  }, []);

  /**
   * Paste clipboard contents with fresh ids, preserved internal edges, and a
   * visual offset. Returns pasted ids (selected afterwards).
   */
  const pasteClipboard = useCallback((): string[] => {
    const cb = clipboardRef.current;
    if (!cb || (cb.triggers.length === 0 && cb.nodes.length === 0)) return [];
    const DX = 48;
    const DY = 48;
    const idMap = new Map<string, string>();
    for (const t of cb.triggers) idMap.set(t.id, newId('trg'));
    for (const n of cb.nodes) idMap.set(n.id, newId('n'));
    const triggers = cb.triggers.map((t) => ({
      ...t,
      id: idMap.get(t.id)!,
      position: { x: (t.position?.x ?? 80) + DX, y: (t.position?.y ?? 80) + DY },
    }));
    const nodes = cb.nodes.map((n) => ({
      ...n,
      id: idMap.get(n.id)!,
      position: { x: (n.position?.x ?? 80) + DX, y: (n.position?.y ?? 80) + DY },
    }));
    const edges = cb.edges
      .filter((e) => idMap.has(e.from) && idMap.has(e.to))
      .map((e) => ({ ...e, id: newId('e'), from: idMap.get(e.from)!, to: idMap.get(e.to)! }));
    dispatch({ type: 'duplicate-items', items: { triggers, nodes, edges } });
    const pasted = [...triggers, ...nodes].map((x) => x.id);
    dispatch({ type: 'box-select', ids: pasted });
    return pasted;
  }, []);

  /** Duplicate the current selection in one undo step. */
  const duplicateSelection = useCallback((): boolean => {
    if (!copySelection()) return false;
    // copySelection updates state async; paste from a synchronous snapshot.
    const def = stateRef.current.definition;
    const ids = new Set(stateRef.current.selectedIds);
    const DX = 48;
    const DY = 48;
    const idMap = new Map<string, string>();
    for (const t of def.triggers) if (ids.has(t.id)) idMap.set(t.id, newId('trg'));
    for (const n of def.nodes) if (ids.has(n.id)) idMap.set(n.id, newId('n'));
    if (idMap.size === 0) return false;
    const triggers = def.triggers
      .filter((t) => idMap.has(t.id))
      .map((t) => {
        const c = stripSensitiveTrigger(t);
        return { ...c, id: idMap.get(t.id)!, position: { x: (t.position?.x ?? 80) + DX, y: (t.position?.y ?? 80) + DY } };
      });
    const nodes = def.nodes
      .filter((n) => idMap.has(n.id))
      .map((n) => {
        const c = stripSensitive(n);
        return { ...c, id: idMap.get(n.id)!, position: { x: (n.position?.x ?? 80) + DX, y: (n.position?.y ?? 80) + DY } };
      });
    const edges = def.edges
      .filter((e) => idMap.has(e.from) && idMap.has(e.to))
      .map((e) => ({ ...e, id: newId('e'), from: idMap.get(e.from)!, to: idMap.get(e.to)! }));
    dispatch({ type: 'duplicate-items', items: { triggers, nodes, edges } });
    dispatch({ type: 'box-select', ids: [...idMap.values()] });
    return true;
  }, [copySelection]);

  return {
    definition: state.definition,
    selection: state.selection,
    selectedIds: state.selectedIds,
    hasMultiSelection: state.selectedIds.length > 1,
    select,
    toggleSelect,
    boxSelect,
    copySelection,
    pasteClipboard,
    duplicateSelection,
    hasClipboard: clipboard !== null && (clipboard.triggers.length > 0 || clipboard.nodes.length > 0),
    dispatch,
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
    undo: () => dispatch({ type: 'undo' }),
    redo: () => dispatch({ type: 'redo' }),
    dirty,
    validation,
    errorsFor,
    pendingEdge,
    setPendingEdge,
    addTrigger,
    addNode,
    connect,
    markSaved,
    clearDraft,
    load: (definition: WorkflowDefinition) => dispatch({ type: 'load', definition }),
  };
}

export type WorkflowEditor = ReturnType<typeof useWorkflowEditor>;
