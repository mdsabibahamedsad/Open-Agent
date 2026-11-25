import { describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api';
import {
  buildAssistantUrl,
  currentRelativeUrl,
  isMissingConversationError,
  normalizeConversationId,
  parseAssistantUrlState,
} from './url-state';

const VALID_UUID = '123e4567-e89b-12d3-a456-426614174000';
const SECOND_UUID = '987fcdeb-51a2-43d7-9abc-111122223333';

describe('url-state', () => {
  describe('normalizeConversationId', () => {
    it('normalizes uppercase and whitespace-padded UUIDs to lowercase', () => {
      expect(normalizeConversationId(VALID_UUID)).toBe(VALID_UUID);
      expect(normalizeConversationId(`  ${VALID_UUID.toUpperCase()}  `)).toBe(VALID_UUID);
    });

    it('rejects empty, numeric, path-like, and truncated identifiers', () => {
      expect(normalizeConversationId('')).toBeNull();
      expect(normalizeConversationId('   ')).toBeNull();
      expect(normalizeConversationId('12345')).toBeNull();
      expect(normalizeConversationId('abc')).toBeNull();
      expect(normalizeConversationId('../etc/passwd')).toBeNull();
      expect(normalizeConversationId('123e4567-e89b-12d3-a456')).toBeNull();
    });
  });

  describe('parseAssistantUrlState', () => {
    it('returns absent when conversation param is missing', () => {
      expect(parseAssistantUrlState('')).toEqual({
        conversation: { status: 'absent', id: null },
        prompt: null,
      });
    });

    it('parses valid lowercase and uppercase conversation UUIDs', () => {
      expect(parseAssistantUrlState(`?conversation=${VALID_UUID}`)).toEqual({
        conversation: { status: 'valid', id: VALID_UUID },
        prompt: null,
      });
      expect(parseAssistantUrlState(`?conversation=${VALID_UUID.toUpperCase()}`)).toEqual({
        conversation: { status: 'valid', id: VALID_UUID },
        prompt: null,
      });
    });

    it('marks empty, whitespace, invalid, and malformed-encoded values as invalid', () => {
      expect(parseAssistantUrlState('?conversation=')).toEqual({
        conversation: { status: 'invalid', id: null, raw: '' },
        prompt: null,
      });
      expect(parseAssistantUrlState('?conversation=%20%20')).toEqual({
        conversation: { status: 'invalid', id: null, raw: '  ' },
        prompt: null,
      });
      expect(parseAssistantUrlState('?conversation=not-a-uuid')).toEqual({
        conversation: { status: 'invalid', id: null, raw: 'not-a-uuid' },
        prompt: null,
      });
      expect(parseAssistantUrlState('?conversation=%E0%A4%A').conversation.status).toBe('invalid');
    });

    it('follows first-value semantics for duplicate conversation parameters', () => {
      expect(
        parseAssistantUrlState(`?conversation=${VALID_UUID}&conversation=${SECOND_UUID}`),
      ).toEqual({
        conversation: { status: 'valid', id: VALID_UUID },
        prompt: null,
      });
      expect(parseAssistantUrlState(`?conversation=&conversation=${VALID_UUID}`)).toEqual({
        conversation: { status: 'invalid', id: null, raw: '' },
        prompt: null,
      });
      expect(parseAssistantUrlState(`?conversation=bad&conversation=${VALID_UUID}`)).toEqual({
        conversation: { status: 'invalid', id: null, raw: 'bad' },
        prompt: null,
      });
    });

    it('parses prompt alongside conversation and ignores empty prompt', () => {
      expect(
        parseAssistantUrlState(`?conversation=${VALID_UUID}&prompt=Build%20a%20flow`),
      ).toEqual({
        conversation: { status: 'valid', id: VALID_UUID },
        prompt: 'Build a flow',
      });
      expect(parseAssistantUrlState('?prompt=')).toEqual({
        conversation: { status: 'absent', id: null },
        prompt: null,
      });
    });
  });

  describe('buildAssistantUrl', () => {
    it('clears prompt while preserving conversation, unrelated query params, pathname, and hash', () => {
      const next = buildAssistantUrl(
        {
          pathname: '/assistant',
          search: `?conversation=${VALID_UUID}&prompt=Hello&tab=debug`,
          hash: '#top',
        },
        { clearPrompt: true },
      );
      expect(next).toBe(`/assistant?conversation=${VALID_UUID}&tab=debug#top`);
    });

    it('sets and removes conversation while preserving unrelated query params and hash', () => {
      const withId = buildAssistantUrl(
        {
          pathname: '/assistant',
          search: '?tab=debug&conversation=old&conversation=older',
          hash: '#sec',
        },
        { conversationId: SECOND_UUID },
      );
      expect(withId).toBe(`/assistant?tab=debug&conversation=${SECOND_UUID}#sec`);

      const cleared = buildAssistantUrl(
        {
          pathname: '/assistant',
          search: `?tab=debug&conversation=${SECOND_UUID}`,
          hash: '#sec',
        },
        { conversationId: null },
      );
      expect(cleared).toBe('/assistant?tab=debug#sec');
    });

    it('drops trailing question mark when all query params are removed', () => {
      expect(
        buildAssistantUrl(
          { pathname: '/assistant', search: `?conversation=${VALID_UUID}`, hash: '' },
          { conversationId: null },
        ),
      ).toBe('/assistant');
      expect(
        currentRelativeUrl({ pathname: '/assistant', search: '?foo=1', hash: '#h' }),
      ).toBe('/assistant?foo=1#h');
    });
  });

  describe('isMissingConversationError', () => {
    it('returns true for 404 and conversation_id 422 validation errors', () => {
      expect(isMissingConversationError(new ApiError('Not found', { status: 404, code: 'NOT_FOUND' }))).toBe(
        true,
      );
      expect(
        isMissingConversationError(
          new ApiError('Invalid request', {
            status: 422,
            code: 'VALIDATION_ERROR',
            details: [{ field: 'path.conversation_id', code: 'VALIDATION_ERROR', message: 'Input should be a valid UUID' }],
          }),
        ),
      ).toBe(true);
      expect(
        isMissingConversationError(
          new ApiError('Invalid request', { status: 422, code: 'VALIDATION_ERROR' }),
        ),
      ).toBe(true);
    });

    it('returns false for non-conversation 422, network, 5xx, auth, rate-limit, and unknown errors', () => {
      expect(
        isMissingConversationError(
          new ApiError('Invalid org', {
            status: 422,
            code: 'VALIDATION_ERROR',
            details: [{ field: 'path.organization_id', code: 'VALIDATION_ERROR', message: 'Invalid UUID' }],
          }),
        ),
      ).toBe(false);
      expect(isMissingConversationError(new ApiError('Network', { status: 0, code: 'NETWORK_ERROR' }))).toBe(
        false,
      );
      expect(isMissingConversationError(new ApiError('Server', { status: 500, code: 'SERVER_ERROR' }))).toBe(
        false,
      );
      expect(isMissingConversationError(new ApiError('Unauthorized', { status: 401, code: 'UNAUTHORIZED' }))).toBe(
        false,
      );
      expect(isMissingConversationError(new ApiError('Forbidden', { status: 403, code: 'FORBIDDEN' }))).toBe(
        false,
      );
      expect(isMissingConversationError(new ApiError('Rate limit', { status: 429, code: 'RATE_LIMITED' }))).toBe(
        false,
      );
      expect(isMissingConversationError(new Error('Generic error'))).toBe(false);
    });
  });
});
