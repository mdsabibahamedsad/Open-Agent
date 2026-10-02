'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}

export function Dialog({ open, onClose, title, description, children, footer, wide }: DialogProps) {
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    ref.current?.querySelector<HTMLElement>('button, [href], input, select, textarea')?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-modal flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden />
      <div
        ref={ref}
        className={cn('relative w-full rounded-lg border bg-card p-6 shadow-lg animate-fade-in', wide ? 'max-w-2xl' : 'max-w-lg')}
      >
        <h2 className="text-lg font-semibold">{title}</h2>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
        <div className="mt-4">{children}</div>
        {footer && <div className="mt-6 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = 'Confirm',
  danger = false,
  requireText,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  description?: string;
  confirmLabel?: string;
  danger?: boolean;
  requireText?: string;
}) {
  const [input, setInput] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const valid = !requireText || input.trim() === requireText;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      footer={
        <>
          <button onClick={onClose} className="rounded-md border border-input px-4 py-2 text-sm hover:bg-accent">
            Cancel
          </button>
          <button
            disabled={!valid || busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
                onClose();
              } finally {
                setBusy(false);
              }
            }}
            className={cn(
              'rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-50',
              danger ? 'bg-destructive hover:bg-destructive/90' : 'bg-primary hover:bg-primary/90',
            )}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </>
      }
    >
      {requireText && (
        <div className="space-y-2">
          <p className="text-sm">
            Type <span className="oa-code">{requireText}</span> to confirm.
          </p>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            aria-label="Confirmation text"
          />
        </div>
      )}
    </Dialog>
  );
}
