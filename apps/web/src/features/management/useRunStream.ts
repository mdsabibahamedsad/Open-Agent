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

/** SSE live updates with graceful fallback (caller keeps polling). */
export function useRunStream(orgId: string | null, runId: string | null) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sinceRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!orgId || !runId) return;
    const url = streamUrl(orgId, runId, sinceRef.current);
    if (!url || typeof EventSource === 'undefined') {
      setError('SSE unsupported; using polling.');
      return;
    }
    const source = new EventSource(url);
    setError(null);
    source.onopen = () => setConnected(true);
    source.onerror = () => {
      setConnected(false);
      setError('Stream interrupted; using polling.');
      source.close();
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
    return () => {
      source.close();
      setConnected(false);
    };
  }, [orgId, runId]);

  return { events, connected, error };
}
