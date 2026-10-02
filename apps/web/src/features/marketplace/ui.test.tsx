import * as React from 'react';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  ChangelogView,
  FavoriteButton,
  HealthBadge,
  InstallStateButton,
  ListingCardView,
  PricingBadge,
  RatingDistribution,
  RatingStars,
  VerificationBadge,
  resolveInstallState,
} from './ui';
import type { ListingCard } from '@/lib/marketplace';

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function listing(overrides: Partial<ListingCard> = {}): ListingCard {
  return {
    id: 'listing-1',
    marketplace_id: 'mkt-1',
    package_id: 'pkg-1',
    publisher_id: 'pub-1',
    publisher_slug: 'acme',
    publisher_name: 'Acme',
    publisher_verification: 'VERIFIED',
    slug: 'research-workforce',
    title: 'Research Workforce',
    short_description: 'Deep research team',
    full_description: 'Deep research team.',
    icon: '',
    banner: '',
    screenshots: [],
    videos: [],
    category: 'research',
    license: 'Apache-2.0',
    pricing_model: 'FREE',
    compatibility: {},
    requirements: {},
    trust_level: 'VERIFIED',
    security_status: 'LOW',
    published_version_id: 'v-1',
    published_version: '1.0.0',
    status: 'PUBLISHED',
    status_reason: '',
    badges: {},
    rating_average: 4.5,
    rating_count: 10,
    rating_distribution: { '5': 7, '4': 2, '3': 1, '2': 0, '1': 0 },
    verified_review_count: 8,
    install_count: 42,
    successful_install_count: 40,
    active_install_count: 30,
    favorite_count: 5,
    view_count: 100,
    installed: false,
    installed_version: '',
    favorite: false,
    published_at: '2026-09-01T00:00:00Z',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    ...overrides,
  };
}

describe('marketplace ui', () => {
  it('renders listing card from real backend fields only', () => {
    renderWithClient(<ListingCardView listing={listing()} />);
    expect(screen.getByText('Research Workforce')).toBeInTheDocument();
    expect(screen.getByText(/acme/i)).toBeInTheDocument();
    expect(screen.getByText(/42 installs/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/secret|password|token/i);
  });

  it('labels editorial placement explicitly', () => {
    renderWithClient(<ListingCardView listing={listing({ badges: { featured: true } })} />);
    expect(screen.getByText('Featured')).toBeInTheDocument();
  });

  it('resolves install states from backend state', () => {
    expect(resolveInstallState({ status: 'PUBLISHED', installed: false, installed_version: '', published_version: '1.0.0' }).state).toBe('install');
    expect(resolveInstallState({ status: 'PUBLISHED', installed: true, installed_version: '1.0.0', published_version: '1.0.0' }).state).toBe('installed');
    expect(resolveInstallState({ status: 'PUBLISHED', installed: true, installed_version: '1.0.0', published_version: '1.1.0' }).state).toBe('update-available');
    expect(resolveInstallState({ status: 'REVOKED', installed: false, installed_version: '', published_version: '1.0.0' }).state).toBe('revoked');
    expect(resolveInstallState({ status: 'SUSPENDED', installed: false, installed_version: '', published_version: '1.0.0' }).state).toBe('blocked');
  });

  it('never shows Installed before backend confirmation', () => {
    renderWithClient(
      <InstallStateButton
        listing={{ status: 'PUBLISHED', installed: false, installed_version: '', published_version: '1.0.0' }}
        onInstall={() => {}}
      />,
    );
    expect(screen.getByRole('button', { name: /install/i })).toBeInTheDocument();
    expect(screen.queryByText('Installed')).not.toBeInTheDocument();
  });

  it('renders verification badge states', () => {
    renderWithClient(<VerificationBadge status="VERIFIED" />);
    expect(screen.getByText(/verified publisher/i)).toBeInTheDocument();
  });

  it('renders pricing honestly', () => {
    renderWithClient(<PricingBadge pricingModel="FREE" />);
    expect(screen.getByText('Free')).toBeInTheDocument();
  });

  it('renders rating stars and distribution', () => {
    renderWithClient(
      <>
        <RatingStars average={4.5} count={10} />
        <RatingDistribution distribution={{ '5': 7, '4': 2, '3': 1, '2': 0, '1': 0 }} />
      </>,
    );
    expect(screen.getByLabelText(/rated 4.5 out of 5 from 10 reviews/i)).toBeInTheDocument();
  });

  it('renders health badge without opaque scores', () => {
    renderWithClient(<HealthBadge status="AT_RISK" />);
    expect(screen.getByText('AT_RISK')).toBeInTheDocument();
  });

  it('toggles favorite with pressed state', () => {
    renderWithClient(<FavoriteButton favorite={false} count={5} onToggle={() => {}} />);
    expect(screen.getByRole('button', { name: /save to favorites/i })).toHaveAttribute('aria-pressed', 'false');
  });

  it('highlights breaking and security changelog sections', () => {
    renderWithClient(
      <ChangelogView changelog={{ breaking: ['Removed legacy tool'], security: ['Patched XSS'], added: ['New agent'] }} />,
    );
    expect(screen.getByText('Breaking changes')).toBeInTheDocument();
    expect(screen.getByText('Security')).toBeInTheDocument();
    expect(screen.getByText(/removed legacy tool/i)).toBeInTheDocument();
  });
});
