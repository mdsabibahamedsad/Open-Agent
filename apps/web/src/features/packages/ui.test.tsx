import * as React from 'react';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { catalogEntryToCard, RiskBadge, SecurityReport, TrustBadge } from './ui';

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe('packages ui', () => {
  it('maps catalog entries to cards without leaking internals', () => {
    const card = catalogEntryToCard({
      package_id: 'pkg-1',
      name: 'Research Workforce',
      description: 'Deep research team',
      type: 'WORKFORCE',
      version: '1.0.0',
      trust: 'CORE',
      official: true,
      categories: ['Research'],
      tags: ['research'],
    });
    expect(card).toMatchObject({
      id: 'pkg-1',
      name: 'Research Workforce',
      package_type: 'WORKFORCE',
      latest_version: '1.0.0',
    });
    expect(JSON.stringify(card)).not.toMatch(/secret|password|token/i);
  });

  it('renders official trust badge', () => {
    renderWithClient(<TrustBadge trust="COMMUNITY" official />);
    expect(screen.getByText(/official/i)).toBeInTheDocument();
  });

  it('renders risk badge', () => {
    renderWithClient(<RiskBadge risk="HIGH" />);
    expect(screen.getByText(/high risk/i)).toBeInTheDocument();
  });

  it('renders security findings with severities', () => {
    renderWithClient(
      <SecurityReport
        risk="MEDIUM"
        findings={[
          { code: 'MISSING_APPROVAL', path: 'security', severity: 'WARNING', message: 'Declare approvals' },
          { code: 'SECRET_LEAK', path: '$.x', severity: 'BLOCKER', message: 'Raw secret' },
        ]}
      />,
    );
    expect(screen.getByText(/missing_approval/i)).toBeInTheDocument();
    expect(screen.getByText(/raw secret/i)).toBeInTheDocument();
  });
});
