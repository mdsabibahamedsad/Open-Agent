'use client';

import * as React from 'react';
import { Bell } from 'lucide-react';

interface Notice {
  id: string;
  title: string;
  body?: string;
  time: string;
}

const SEED: Notice[] = [
  { id: '1', title: 'Welcome to OpenAgent', body: 'Set up your organization to get started.', time: 'now' },
];

export function Notifications() {
  const [open, setOpen] = React.useState(false);
  const [items] = React.useState<Notice[]>(SEED);
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Notifications (${items.length} unread)`}
        className="relative rounded-full p-2 hover:bg-accent"
      >
        <Bell className="h-5 w-5" aria-hidden />
        {items.length > 0 && (
          <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-destructive" aria-hidden />
        )}
      </button>
      {open && (
        <div role="dialog" aria-label="Notifications" className="absolute right-0 top-full z-dropdown mt-2 w-80 rounded-md border bg-popover shadow-md">
          <div className="border-b px-4 py-2.5 font-medium text-sm">Notifications</div>
          <ul className="max-h-80 overflow-y-auto p-2">
            {items.map((n) => (
              <li key={n.id} className="rounded-md px-3 py-2 hover:bg-accent">
                <p className="text-sm font-medium">{n.title}</p>
                {n.body && <p className="text-xs text-muted-foreground">{n.body}</p>}
                <p className="mt-0.5 text-[11px] text-muted-foreground">{n.time}</p>
              </li>
            ))}
          </ul>
          <p className="border-t px-4 py-2 text-[11px] text-muted-foreground">
            Execution alerts and approvals will appear here in future phases.
          </p>
        </div>
      )}
    </div>
  );
}
