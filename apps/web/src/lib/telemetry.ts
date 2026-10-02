// Minimal frontend telemetry: route, request_id, error, component, timestamp.
// No personal data. Forwards to /api/telemetry when available; otherwise console.

export interface TelemetryEvent {
  route: string;
  request_id?: string;
  error?: string;
  component?: string;
  extra?: Record<string, string>;
}

export function captureEvent(evt: TelemetryEvent): void {
  const payload = { ...evt, timestamp: new Date().toISOString(), browser: typeof navigator !== 'undefined' ? navigator.userAgent.slice(0, 160) : 'ssr' };
  try {
    if (typeof window !== 'undefined' && 'fetch' in window) {
      fetch('/api/telemetry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        keepalive: true,
      }).catch(() => {});
    }
  } catch {
    /* noop */
  }
  if (process.env.NODE_ENV === 'development') {
    console.debug('[telemetry]', payload);
  }
}

export function captureError(error: unknown, component?: string, requestId?: string): void {
  captureEvent({
    route: typeof window !== 'undefined' ? window.location.pathname : 'ssr',
    error: error instanceof Error ? `${error.name}: ${error.message}`.slice(0, 500) : String(error).slice(0, 500),
    component,
    request_id: requestId,
  });
}
