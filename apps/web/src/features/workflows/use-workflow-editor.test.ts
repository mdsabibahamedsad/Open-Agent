import { createEditorState, editorReducer } from './use-workflow-editor';
import { emptyDefinition } from './types';
import type { WorkflowDefinition } from './types';

function withNode(): WorkflowDefinition {
  return {
    ...emptyDefinition(),
    triggers: [{ id: 'trg_1', type: 'manual', name: 'Start', config: {} }],
    nodes: [
      { id: 'n_1', type: 'delay', name: 'Wait', position: { x: 0, y: 0 }, config: { duration_seconds: 5 } },
    ],
    edges: [{ id: 'e_1', from: 'trg_1', to: 'n_1', condition: { when: 'always' } }],
  };
}

describe('editorReducer', () => {
  it('adds nodes and selects them via separate select action', () => {
    let s = createEditorState(withNode());
    s = editorReducer(s, {
      type: 'add-node',
      node: { id: 'n_2', type: 'delay', name: 'Wait 2', config: { duration_seconds: 10 } },
    });
    expect(s.definition.nodes).toHaveLength(2);
    expect(s.past).toHaveLength(1);
  });

  it('moves without history, then commits a single undo entry', () => {
    let s = createEditorState(withNode());
    const before = s.definition;
    s = editorReducer(s, { type: 'move-item', id: 'n_1', x: 50, y: 60 });
    s = editorReducer(s, { type: 'move-item', id: 'n_1', x: 90, y: 10 });
    expect(s.past).toHaveLength(0);
    expect(s.definition.nodes[0].position).toEqual({ x: 90, y: 10 });
    s = editorReducer(s, { type: 'commit-move', before });
    expect(s.past).toHaveLength(1);
    // No-op commit does nothing.
    s = editorReducer(s, { type: 'commit-move', before: s.definition });
    expect(s.past).toHaveLength(1);
  });

  it('supports undo/redo round-trip', () => {
    let s = createEditorState(withNode());
    s = editorReducer(s, { type: 'delete-selection' }); // nothing selected -> noop
    expect(s.definition.nodes).toHaveLength(1);
    s = editorReducer(s, { type: 'select', selection: { kind: 'node', id: 'n_1' } });
    s = editorReducer(s, { type: 'delete-selection' });
    expect(s.definition.nodes).toHaveLength(0);
    expect(s.definition.edges).toHaveLength(0); // incident edges removed
    s = editorReducer(s, { type: 'undo' });
    expect(s.definition.nodes).toHaveLength(1);
    s = editorReducer(s, { type: 'redo' });
    expect(s.definition.nodes).toHaveLength(0);
  });

  it('rejects duplicate edges', () => {
    let s = createEditorState(withNode());
    const dup = { id: 'e_2', from: 'trg_1', to: 'n_1', condition: { when: 'always' as const } };
    const next = editorReducer(s, { type: 'add-edge', edge: dup });
    expect(next).toBe(s); // unchanged reference
  });

  it('tracks multi-selection via toggle and box select', () => {
    let s = createEditorState(withNode());
    s = editorReducer(s, {
      type: 'add-node',
      node: { id: 'n_2', type: 'delay', name: 'Wait 2', config: { duration_seconds: 1 } },
    });
    s = editorReducer(s, { type: 'toggle-select', selection: { kind: 'node', id: 'n_1' } });
    s = editorReducer(s, { type: 'toggle-select', selection: { kind: 'node', id: 'n_2' } });
    expect(s.selectedIds).toEqual(['n_1', 'n_2']);
    // Toggling off removes and repoints the primary selection.
    s = editorReducer(s, { type: 'toggle-select', selection: { kind: 'node', id: 'n_1' } });
    expect(s.selectedIds).toEqual(['n_2']);
    expect(s.selection?.id).toBe('n_2');
    // Box select replaces the set.
    s = editorReducer(s, { type: 'box-select', ids: ['n_1'] });
    expect(s.selectedIds).toEqual(['n_1']);
    // Single select resets multi-selection.
    s = editorReducer(s, { type: 'select', selection: null });
    expect(s.selectedIds).toEqual([]);
  });

  it('deletes every selected id with incident edges', () => {
    let s = createEditorState(withNode());
    s = editorReducer(s, { type: 'box-select', ids: ['trg_1', 'n_1'] });
    s = editorReducer(s, { type: 'delete-selection' });
    expect(s.definition.triggers).toHaveLength(0);
    expect(s.definition.nodes).toHaveLength(0);
    expect(s.definition.edges).toHaveLength(0);
    expect(s.selectedIds).toEqual([]);
  });

  it('duplicates items with fresh ids in one history entry', () => {
    let s = createEditorState(withNode());
    const before = s.past.length;
    s = editorReducer(s, { type: 'box-select', ids: ['trg_1', 'n_1'] });
    const items = {
      triggers: [{ id: 'trg_2', type: 'manual' as const, name: 'Start copy', config: {} }],
      nodes: [{ id: 'n_2', type: 'delay' as const, name: 'Wait copy', config: { duration_seconds: 5 } }],
      edges: [{ id: 'e_2', from: 'trg_2', to: 'n_2', condition: { when: 'always' as const } }],
    };
    s = editorReducer(s, { type: 'duplicate-items', items });
    expect(s.definition.triggers).toHaveLength(2);
    expect(s.definition.nodes).toHaveLength(2);
    expect(s.definition.edges).toHaveLength(2);
    expect(s.past.length).toBe(before + 1);
  });
});
