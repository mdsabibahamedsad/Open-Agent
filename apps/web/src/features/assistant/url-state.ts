import { ApiError } from '@/lib/api';

export const CONVERSATION_PARAM = 'conversation';
export const PROMPT_PARAM = 'prompt';

export const MISSING_CONVERSATION_NOTICE =
  'That conversation could not be found or was deleted. Started a new chat.';

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type ConversationParamState =
  | { status: 'absent'; id: null }
  | { status: 'valid'; id: string }
  | { status: 'invalid'; id: null; raw: string };

export interface AssistantUrlState {
  conversation: ConversationParamState;
  prompt: string | null;
}

export interface RelativeUrlParts {
  pathname: string;
  search: string;
  hash: string;
}

export interface AssistantUrlUpdates {
  conversationId?: string | null;
  clearPrompt?: boolean;
}

/**
 * Validate and normalize a backend conversation UUID.
 * The API stores and serializes UUIDs in canonical lowercase form, so
 * uppercase deep links are normalized to match sidebar and detail responses.
 */
export function normalizeConversationId(raw: string): string | null {
  const trimmed = raw.trim();
  if (!UUID_PATTERN.test(trimmed)) return null;
  return trimmed.toLowerCase();
}

/**
 * Parse `?conversation=` and `?prompt=` from a query string without throwing on
 * malformed percent-encoding. Duplicate `?conversation=` keys follow
 * `URLSearchParams.get()` first-value semantics.
 */
export function parseAssistantUrlState(search: string): AssistantUrlState {
  const params = new URLSearchParams(search);
  const conversationValues = params.getAll(CONVERSATION_PARAM);

  let conversation: ConversationParamState;
  if (conversationValues.length === 0) {
    conversation = { status: 'absent', id: null };
  } else {
    const first = conversationValues[0];
    const normalized = normalizeConversationId(first);
    conversation = normalized
      ? { status: 'valid', id: normalized }
      : { status: 'invalid', id: null, raw: first };
  }

  const rawPrompt = params.get(PROMPT_PARAM);
  const prompt = rawPrompt && rawPrompt.length > 0 ? rawPrompt : null;

  return { conversation, prompt };
}

/**
 * Return a relative URL string while preserving unrelated query parameters,
 * pathname, and hash fragment.
 */
export function buildAssistantUrl(
  current: RelativeUrlParts,
  updates: AssistantUrlUpdates,
): string {
  const pathname = current.pathname || '/assistant';
  const params = new URLSearchParams(current.search);

  if (updates.clearPrompt) {
    params.delete(PROMPT_PARAM);
  }

  if ('conversationId' in updates) {
    if (updates.conversationId) {
      params.set(CONVERSATION_PARAM, updates.conversationId);
    } else {
      params.delete(CONVERSATION_PARAM);
    }
  }

  const query = params.toString();
  return `${pathname}${query ? `?${query}` : ''}${current.hash}`;
}

export function currentRelativeUrl(current: RelativeUrlParts): string {
  const pathname = current.pathname || '/assistant';
  return `${pathname}${current.search}${current.hash}`;
}

/**
 * Distinguish missing/deleted/invalid-id conversation responses (404 or
 * conversation_id 422) from transient network, 5xx, auth, or rate-limit failures.
 */
export function isMissingConversationError(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false;
  if (err.kind === 'NOT_FOUND' || err.status === 404) return true;
  if (err.status === 422) {
    if (!err.details || err.details.length === 0) return true;
    return err.details.some((detail) => detail.field?.includes('conversation_id'));
  }
  return false;
}
