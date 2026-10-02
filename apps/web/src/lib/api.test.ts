import { ApiError, toUserMessage } from './api';

describe('ApiError mapping', () => {
  it('maps 401 to UNAUTHORIZED with sign-in message', () => {
    const e = new ApiError('x', { status: 401, code: 'UNAUTHORIZED' });
    expect(e.kind).toBe('UNAUTHORIZED');
    expect(toUserMessage(e)).toMatch(/sign in/i);
  });

  it('maps 403 to FORBIDDEN', () => {
    const e = new ApiError('x', { status: 403, code: 'FORBIDDEN' });
    expect(e.kind).toBe('FORBIDDEN');
    expect(toUserMessage(e)).toMatch(/permission/i);
  });

  it('maps 404/409/429/500', () => {
    expect(new ApiError('x', { status: 404, code: 'N' }).kind).toBe('NOT_FOUND');
    expect(new ApiError('x', { status: 409, code: 'C' }).kind).toBe('CONFLICT');
    expect(new ApiError('x', { status: 429, code: 'R' }).kind).toBe('RATE_LIMITED');
    expect(new ApiError('x', { status: 500, code: 'S' }).kind).toBe('SERVER_ERROR');
  });

  it('prefers first validation detail message', () => {
    const e = new ApiError('Invalid', {
      status: 422,
      code: 'VALIDATION_ERROR',
      details: [{ field: 'email', code: 'invalid', message: 'Enter a valid email.' }],
    });
    expect(toUserMessage(e)).toBe('Enter a valid email.');
  });

  it('handles network errors safely', () => {
    const e = new ApiError('boom', { status: 0, code: 'NETWORK_ERROR' });
    expect(e.kind).toBe('NETWORK_ERROR');
    expect(toUserMessage(e)).toMatch(/network/i);
  });
});
