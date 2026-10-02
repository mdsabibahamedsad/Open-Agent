'use client';

import { useEffect, useRef, useState } from 'react';
import { streamUrl } from './api';

export interface StreamEvent {
  id: string;
  event: string;
  task_id?: string | null;
  agent_id?: string | null;
  payload: Record<string, unknown>;
}

/** SSE live updates with bounded reconnect, then polling fallback.
 *
 * Reconnects with exponential backoff (max 5 attempts, ~15s total budget).
 * After that the caller keeps polling — the backend (PostgreSQL) remains
 * authoritative, so no execution state is lost when the stream drops.
 */
const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_RECONNECT_DELAY_MS = 500;

export function useRunStream(orgId: string | null, runId: string | null) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sinceRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!orgId || !runId) return;
    if (typeof EventSource === 'undefined') {
      setError('SSE unsupported; using polling.');
      return;
    }
    let closed = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let source: EventSource | null = null;

    const connect = () => {
      if (closed) return;
      const url = streamUrl(orgId, runId, sinceRef.current);
      if (!url) {
        setError('SSE unsupported; using polling.');
        return;
      }
      setError(null);
      source = new EventSource(url);
      source.onopen = () => {
        attempts = 0; // reset budget on successful (re)connect
        setConnected(true);
      };
      source.onerror = () => {
        source?.close();
        source = null;
        setConnected(false);
        attempts += 1;
        if (attempts > MAX_RECONNECT_ATTEMPTS || closed) {
          setError('Stream unavailable; using polling.');
          return;
        }
        const delay = Math.min(BASE_RECONNECT_DELAY_MS * 2 ** (attempts - 1), 8000);
        timer = setTimeout(connect, delay);
      };
      source.onmessage = (msg: MessageEvent) => {
        try {
          const data = JSON.parse(msg.data) as StreamEvent;
          if (msg.lastEventId) sinceRef.current = msg.lastEventId;
          setEvents((prev) => [...prev.slice(-199), { ...data, id: msg.lastEventId || data.id }]);
        } catch {
          // Ignore malformed frames; heartbeat comments never reach here.
        }
      };
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      source?.close();
      setConnected(false);
    };
  }, [orgId, runId]);

  return { events, connected, error };
}
