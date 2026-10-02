// MP24: unit tests for the commerce client helpers (no network).

import { describe, expect, it } from 'vitest';
import { formatMinor } from './commerce';

describe('formatMinor', () => {
  it('formats USD cents as dollars', () => {
    expect(formatMinor(999, 'USD')).toContain('9.99');
  });

  it('formats zero-decimal currencies without fractions', () => {
    expect(formatMinor(500, 'JPY')).toContain('500');
    expect(formatMinor(500, 'JPY')).not.toContain('.');
  });

  it('formats zero amounts', () => {
    expect(formatMinor(0, 'USD')).toContain('0.00');
  });

  it('falls back for unknown currencies without throwing', () => {
    expect(() => formatMinor(100, 'XXX' as string)).not.toThrow();
  });
});
