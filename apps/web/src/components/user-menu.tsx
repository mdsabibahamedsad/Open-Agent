'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import { useToast } from '@/components/ui/toast';
import { Avatar } from '@/components/ui/avatar';
import { useTheme } from 'next-themes';
import { LogOut, Settings, User, Keyboard, ShieldCheck, Moon, Sun, Monitor } from 'lucide-react';

export function UserMenu() {
  const { user, logout } = useAuth();
  const { toast } = useToast();
  const { theme, setTheme } = useTheme();
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, []);

  const initials = (user?.display_name ?? user?.email ?? 'U').slice(0, 2).toUpperCase();

  const doLogout = async () => {
    await logout();
    toast({ kind: 'success', title: 'Signed out' });
    router.push('/login');
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        className="rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Avatar fallback={initials} className="h-9 w-9" />
      </button>
      {open && (
        <div role="menu" aria-label="Account" className="absolute right-0 top-full z-dropdown mt-2 w-64 rounded-md border bg-popover p-1 shadow-md">
          <div className="px-3 py-2">
            <p className="truncate text-sm font-medium">{user?.display_name ?? 'User'}</p>
            <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
            {(user?.is_platform_owner || user?.is_superadmin) && (
              <p className="mt-1 inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                <ShieldCheck className="h-3 w-3" /> Platform owner
              </p>
            )}
          </div>
          <div className="my-1 h-px bg-muted" />
          <MenuLink href="/account" icon={<User className="h-4 w-4" />} label="Profile" onClick={() => setOpen(false)} />
          <MenuLink href="/settings" icon={<Settings className="h-4 w-4" />} label="Account settings" onClick={() => setOpen(false)} />
          <MenuLink href="/settings?tab=shortcuts" icon={<Keyboard className="h-4 w-4" />} label="Keyboard shortcuts" onClick={() => setOpen(false)} />
          <div className="my-1 h-px bg-muted" />
          <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground">Theme</div>
          <div className="flex gap-1 px-2 pb-1">
            {[
              { v: 'light', icon: <Sun className="h-3.5 w-3.5" />, label: 'Light' },
              { v: 'dark', icon: <Moon className="h-3.5 w-3.5" />, label: 'Dark' },
              { v: 'system', icon: <Monitor className="h-3.5 w-3.5" />, label: 'System' },
            ].map((t) => (
              <button
                key={t.v}
                onClick={() => setTheme(t.v)}
                aria-pressed={theme === t.v}
                className={`flex flex-1 items-center justify-center gap-1 rounded-sm px-2 py-1.5 text-xs ${theme === t.v ? 'bg-accent font-medium' : 'hover:bg-accent'}`}
              >
                {t.icon}{t.label}
              </button>
            ))}
          </div>
          <div className="my-1 h-px bg-muted" />
          <button
            role="menuitem"
            onClick={doLogout}
            className="flex w-full items-center gap-2 rounded-sm px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10"
          >
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

function MenuLink({ href, icon, label, onClick }: { href: string; icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <Link
      href={href}
      role="menuitem"
      onClick={onClick}
      className="flex items-center gap-2 rounded-sm px-3 py-1.5 text-sm hover:bg-accent"
    >
      {icon}{label}
    </Link>
  );
}
