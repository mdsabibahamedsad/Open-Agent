import * as React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { NodePalette } from './NodePalette';
import type { WorkflowEditor } from '@/features/workflows/use-workflow-editor';

function stubEditor(): WorkflowEditor {
  return {
    addTrigger: () => 'trg_x',
    addNode: () => 'n_x',
  } as unknown as WorkflowEditor;
}

describe('NodePalette', () => {
  it('renders category groups and all required types', () => {
    render(<NodePalette editor={stubEditor()} />);
    expect(screen.getByRole('heading', { name: 'Palette' })).toBeInTheDocument();
    for (const heading of ['Triggers', 'Logic', 'Data', 'AI', 'Tools', 'HTTP', 'Human', 'Utilities']) {
      expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: /add ai prompt to canvas/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add switch \/ router to canvas/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add merge to canvas/i })).toBeInTheDocument();
  });

  it('filters by search text', () => {
    render(<NodePalette editor={stubEditor()} />);
    fireEvent.change(screen.getByRole('textbox', { name: /search node palette/i }), {
      target: { value: 'approv' },
    });
    expect(screen.getByRole('button', { name: /add approval to canvas/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add delay to canvas/i })).not.toBeInTheDocument();
  });

  it('filters by category', () => {
    render(<NodePalette editor={stubEditor()} />);
    fireEvent.change(screen.getByRole('combobox', { name: /filter by category/i }), {
      target: { value: 'Data' },
    });
    expect(screen.getByRole('button', { name: /add filter to canvas/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add approval to canvas/i })).not.toBeInTheDocument();
  });

  it('adds nodes through the plus button', () => {
    const editor = stubEditor();
    const addNode = vi.fn(() => 'n_1');
    (editor as unknown as { addNode: () => string }).addNode = addNode;
    render(<NodePalette editor={editor} />);
    fireEvent.click(screen.getByRole('button', { name: /add delay to canvas/i }));
    expect(addNode).toHaveBeenCalledWith('delay');
  });
});
