import * as React from 'react';
import { render, screen } from '@testing-library/react';
import { EmptyState, ErrorState } from './states';
import { Button } from './button';

describe('states', () => {
  it('renders empty state with action', () => {
    render(
      <EmptyState
        title="No workflows yet"
        description="Create your first workflow."
        action={<Button>Create</Button>}
      />,
    );
    expect(screen.getByRole('heading', { name: /no workflows yet/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /create/i })).toBeInTheDocument();
  });

  it('renders error state with retry and request id', () => {
    const retry = vi.fn();
    render(<ErrorState onRetry={retry} requestId="req_123" />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/req_123/)).toBeInTheDocument();
  });
});
