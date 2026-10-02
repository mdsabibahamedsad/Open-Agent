'use client';

import * as React from 'react';
import { useOrganization } from '@/context/OrganizationContext';
import { Building2, Check, ChevronsUpDown } from 'lucide-react';

export function OrganizationSwitcher({ compact = false }: { compact?: boolean }) {
  const { organizations, currentOrg, switchOrg, isLoading } = useOrganization();
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  if (isLoading) {
    return <div className="h-9 w-44 animate-pulse rounded-md bg-muted" aria-label="Loading organizations" />;
  }

  if (organizations.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-dashed px-3 py-1.5 text-sm text-muted-foreground">
        <Building2 className="h-4 w-4" aria-hidden />
        {!compact && <span>No organization</span>}
      </div>
    );
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Switch organization"
        className="flex max-w-[240px] items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-sm font-medium hover:bg-accent"
      >
        <Building2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        {!compact && (
          <span className="truncate">{currentOrg?.name ?? 'Select org'}</span>
        )}
        <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
      </button>
      {open && (
        <ul role="listbox" aria-label="Organizations" className="absolute left-0 top-full z-dropdown mt-1 max-h-72 w-64 overflow-y-auto rounded-md border bg-popover p-1 shadow-md">
          {organizations.map((o) => (
            <li key={o.id} role="option" aria-selected={o.id === currentOrg?.id}>
              <button
                onClick={() => { switchOrg(o.id); setOpen(false); }}
                className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
              >
                <span className="flex-1 truncate text-left">{o.name}</span>
                {o.id === currentOrg?.id && <Check className="h-4 w-4 text-primary" aria-hidden />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
