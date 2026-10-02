'use client';

import * as React from 'react';
import { Button } from '@/components/ui/button';

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
  label?: string;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Forward to console / future telemetry endpoint. Never log secrets.
    console.error(`[ErrorBoundary:${this.props.label ?? 'app'}]`, error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="rounded-lg border p-8 text-center" role="alert">
          <h2 className="font-semibold">Something went wrong</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            This section failed to render. Try again — the rest of the app is unaffected.
          </p>
          <Button variant="outline" className="mt-4" onClick={() => this.setState({ error: null })}>
            Retry
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
