'use client';

import * as React from 'react';
import {
  Settings2,
  Copy,
  ClipboardPaste,
  Ban,
  CheckCircle2,
  Trash2,
  StickyNote,
  Maximize,
} from 'lucide-react';

export interface MenuTarget {
  kind: 'trigger' | 'node' | 'edge' | 'background';
  id?: string;
  disabled?: boolean;
}

export interface MenuAction {
  id: string;
  label: string;
  icon: React.ReactNode;
  destructive?: boolean;
  disabled?: boolean;
}

export function actionsForTarget(target: MenuTarget, hasClipboard: boolean): MenuAction[] {
  if (target.kind === 'background') {
    return [
      { id: 'paste', label: 'Paste', icon: <ClipboardPaste className="h-4 w-4" />, disabled: !hasClipboard },
      { id: 'fit', label: 'Fit to view', icon: <Maximize className="h-4 w-4" /> },
    ];
  }
  if (target.kind === 'edge') {
    return [{ id: 'delete', label: 'Delete edge', icon: <Trash2 className="h-4 w-4" />, destructive: true }];
  }
  const items: MenuAction[] = [
    { id: 'configure', label: 'Configure', icon: <Settings2 className="h-4 w-4" /> },
    { id: 'duplicate', label: 'Duplicate', icon: <Copy className="h-4 w-4" /> },
    { id: 'copy', label: 'Copy', icon: <Copy className="h-4 w-4" /> },
  ];
  if (target.kind === 'node') {
    items.push(
      target.disabled
        ? { id: 'enable', label: 'Enable', icon: <CheckCircle2 className="h-4 w-4" /> }
        : { id: 'disable', label: 'Disable', icon: <Ban className="h-4 w-4" /> },
    );
  }
  items.push(
    { id: 'note', label: 'Add note', icon: <StickyNote className="h-4 w-4" /> },
    { id: 'delete', label: target.kind === 'trigger' ? 'Delete trigger' : 'Delete node', icon: <Trash2 className="h-4 w-4" />, destructive: true },
  );
  return items;
}

export function CanvasContextMenu({
  x,
  y,
  target,
  hasClipboard,
  onAction,
  onClose,
}: {
  x: number;
  y: number;
  target: MenuTarget;
  hasClipboard: boolean;
  onAction: (actionId: string, target: MenuTarget) => void;
  onClose: () => void;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const actions = actionsForTarget(target, hasClipboard);

  React.useEffect(() => {
    ref.current?.querySelector<HTMLElement>('button:not([disabled])')?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <>
      <div className="fixed inset-0 z-40" onPointerDown={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }} aria-hidden />
      <div
        ref={ref}
        role="menu"
        aria-label={target.kind === 'background' ? 'Canvas menu' : `${target.kind} menu`}
        className="fixed z-50 w-52 rounded-md border bg-popover p-1 shadow-md"
        style={{ left: Math.min(x, window.innerWidth - 220), top: Math.min(y, window.innerHeight - actions.length * 36 - 16) }}
      >
        {actions.map((a) => (
          <button
            key={a.id}
            role="menuitem"
            disabled={a.disabled}
            onClick={() => {
              onAction(a.id, target);
              onClose();
            }}
            className="flex w-full items-center gap-2.5 rounded-sm px-2.5 py-2 text-sm hover:bg-accent disabled:opacity-40 disabled:hover:bg-transparent data-[destructive]:text-destructive"
            data-destructive={a.destructive || undefined}
          >
            {a.icon}
            <span className={a.destructive ? 'text-destructive' : ''}>{a.label}</span>
          </button>
        ))}
      </div>
    </>
  );
}
