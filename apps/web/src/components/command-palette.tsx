'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { useOrganization } from '@/context/OrganizationContext';
import { useTheme } from 'next-themes';
import { Search, Plus, Play, Settings, Moon, Sun, Building2, LayoutDashboard, GitBranch } from 'lucide-react';

interface Command {
  id: string;
  title: string;
  hint?: string;
  icon: React.ReactNode;
  run: () => void;
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = React.useState('');
  const router = useRouter();
  const { organizations, switchOrg } = useOrganization();
  const { setTheme } = useTheme();
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (open) {
      setQuery('');
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open ]);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const go = (href: string) => {
    onClose();
    router.push(href);
  };

  const all: Command[] = [
    { id: 'dash', title: 'Go to Dashboard', icon: <LayoutDashboard className="h-4 w-4" />, run: () => go('/') },
    { id: 'agent', title: 'Create agent', hint: 'Agents', icon: <Plus className="h-4 w-4" />, run: () => go('/agents') },
    { id: 'wf', title: 'Create workflow', hint: 'Workflows', icon: <Plus className="h-4 w-4" />, run: () => go('/workflows/new') },
    { id: 'wflist', title: 'Open workflows', hint: 'Workflows', icon: <GitBranch className="h-4 w-4" />, run: () => go('/workflows') },
    { id: 'runs', title: 'Open executions', hint: 'Runs', icon: <Play className="h-4 w-4" />, run: () => go('/runs') },
    { id: 'settings', title: 'Open settings', icon: <Settings className="h-4 w-4" />, run: () => go('/settings') },
    { id: 'dark', title: 'Toggle dark mode', icon: <Moon className="h-4 w-4" />, run: () => { setTheme('dark'); onClose(); } },
    { id: 'light', title: 'Toggle light mode', icon: <Sun className="h-4 w-4" />, run: () => { setTheme('light'); onClose(); } },
    ...organizations.slice(0, 8).map((o) => ({
      id: `org-${o.id}`,
      title: `Switch to ${o.name}`,
      hint: 'Organization',
      icon: <Building2 className="h-4 w-4" />,
      run: () => { switchOrg(o.id); onClose(); },
    })),
  ];

  const q = query.trim().toLowerCase();
  const filtered = q
    ? all.filter((c) => c.title.toLowerCase().includes(q) || (c.hint ?? '').toLowerCase().includes(q))
    : all;

  const [active, setActive] = React.useState(0);
  React.useEffect(() => setActive(0), [query]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-command flex items-start justify-center p-4 pt-24" role="dialog" aria-modal="true" aria-label="Command palette">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden />
      <div className="relative w-full max-w-lg overflow-hidden rounded-lg border bg-popover shadow-lg animate-fade-in">
        <div className="flex items-center gap-2 border-b px-4">
          <Search className="h-4 w-4 text-muted-foreground" aria-hidden />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, filtered.length - 1)); }
              if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
              if (e.key === 'Enter' && filtered[active]) filtered[active].run();
            }}
            placeholder="Search OpenAgent… (commands, pages, organizations)"
            className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            role="combobox"
            aria-expanded="true"
            aria-controls="cmd-list"
            aria-activedescendant={filtered[active]?.id}
          />
          <kbd className="oa-code">esc</kbd>
        </div>
        <ul id="cmd-list" role="listbox" className="max-h-80 overflow-y-auto p-2">
          {filtered.length === 0 && (
            <li className="px-3 py-6 text-center text-sm text-muted-foreground">No matching commands.</li>
          )}
          {filtered.map((c, i) => (
            <li key={c.id} id={c.id} role="option" aria-selected={i === active}>
              <button
                onMouseEnter={() => setActive(i)}
                onClick={() => c.run()}
                className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm ${i === active ? 'bg-accent text-accent-foreground' : ''}`}
              >
                {c.icon}
                <span className="flex-1 text-left">{c.title}</span>
                {c.hint && <span className="text-xs text-muted-foreground">{c.hint}</span>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
