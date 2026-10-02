'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

export function StatusBadge({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  const s = status.toLowerCase();
  const styles: Record<string, string> = {
    active: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20',
    healthy: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20',
    connected: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20',
    completed: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20',
    success: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20',
    running: 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20',
    queued: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20',
    idle: 'bg-slate-500/10 text-slate-600 dark:text-slate-400 border-slate-500/20',
    paused: 'bg-slate-500/10 text-slate-600 dark:text-slate-400 border-slate-500/20',
    draft: 'bg-slate-500/10 text-slate-600 dark:text-slate-400 border-slate-500/20',
    failed: 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20',
    error: 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20',
    disconnected: 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20',
    cancelled: 'bg-slate-500/10 text-slate-600 dark:text-slate-400 border-slate-500/20',
    published: 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20',
    coming_soon: 'bg-slate-500/10 text-slate-600 dark:text-slate-400 border-slate-500/20',
  };
  const dot: Record<string, string> = {
    active: 'bg-emerald-500', healthy: 'bg-emerald-500', connected: 'bg-emerald-500',
    completed: 'bg-emerald-500', success: 'bg-emerald-500',
    running: 'bg-blue-500', queued: 'bg-amber-500', failed: 'bg-red-500', error: 'bg-red-500',
  };
  const style = styles[s] ?? 'bg-secondary text-secondary-foreground border-border';
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium',
        style,
        className,
      )}
    >
      <span className={cn('h-1.5 w-1.5 rounded-full', dot[s] ?? 'bg-current')} aria-hidden />
      <span className="capitalize">{status.replace(/_/g, ' ')}</span>
    </span>
  );
}
