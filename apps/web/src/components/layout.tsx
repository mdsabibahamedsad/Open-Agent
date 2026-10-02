'use client';

import * as React from 'react';
import { Sidebar } from './sidebar';
import { TopNav } from './top-nav';
import { CommandPalette } from './command-palette';
import { ErrorBoundary } from './error-boundary';
import { cn } from '@/lib/utils';
import { useLocalStorage } from '@/hooks/hooks';

export function Layout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useLocalStorage<boolean>('oa:sidebar-collapsed', false);
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [paletteOpen, setPaletteOpen] = React.useState(false);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        setCollapsed((c) => !c);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [setCollapsed]);

  // Skip link for keyboard users
  return (
    <div className="min-h-screen bg-background">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground"
      >
        Skip to content
      </a>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
      <TopNav
        onMenuClick={() => setMobileOpen(true)}
        sidebarCollapsed={collapsed}
        onOpenPalette={() => setPaletteOpen(true)}
      />
      <main
        id="main-content"
        role="main"
        tabIndex={-1}
        className={cn('min-h-screen pt-16 transition-all duration-200', collapsed ? 'lg:pl-16' : 'lg:pl-64')}
      >
        <div className="oa-page p-4 sm:p-6">
          <ErrorBoundary label="page">
            {children}
          </ErrorBoundary>
        </div>
      </main>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setMobileOpen(false)} aria-hidden />
          <Sidebar mobile collapsed={false} onToggle={() => setMobileOpen(false)} />
        </div>
      )}

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
