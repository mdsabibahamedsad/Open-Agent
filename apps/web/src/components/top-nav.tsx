'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { Menu, Search } from 'lucide-react';
import { OrganizationSwitcher } from '@/components/org-switcher';
import { Notifications } from '@/components/notifications';
import { UserMenu } from '@/components/user-menu';
import { useTheme } from 'next-themes';
import { Sun, Moon } from 'lucide-react';

interface TopNavProps {
  onMenuClick?: () => void;
  sidebarCollapsed?: boolean;
  onOpenPalette?: () => void;
}

export function TopNav({ onMenuClick, sidebarCollapsed, onOpenPalette }: TopNavProps) {
  const { theme, setTheme } = useTheme();

  return (
    <header
      role="banner"
      className={cn(
        'fixed right-0 top-0 z-30 h-16 border-b bg-background/95 backdrop-blur transition-all duration-200 supports-[backdrop-filter]:bg-background/60',
        'left-0 lg:left-64',
        sidebarCollapsed && 'lg:left-16',
      )}
    >
      <div className="flex h-full items-center gap-2 px-3 sm:gap-3 sm:px-4">
        <button
          onClick={onMenuClick}
          aria-label="Open navigation menu"
          className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-foreground lg:hidden"
        >
          <Menu className="h-5 w-5" aria-hidden />
        </button>

        <OrganizationSwitcher />

        <button
          onClick={onOpenPalette}
          aria-label="Open command palette (Control K)"
          className="ml-1 hidden min-w-0 flex-1 items-center gap-2 rounded-md border bg-muted/50 px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground md:flex md:max-w-sm"
        >
          <Search className="h-4 w-4 shrink-0" aria-hidden />
          <span className="truncate">Search or command…</span>
          <kbd className="oa-code ml-auto shrink-0">⌘K</kbd>
        </button>
        <button
          onClick={onOpenPalette}
          aria-label="Open search"
          className="rounded-md p-2 text-muted-foreground hover:bg-accent md:hidden"
        >
          <Search className="h-5 w-5" aria-hidden />
        </button>

        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          <button
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            aria-label="Toggle color theme"
            className="rounded-full p-2 hover:bg-accent"
          >
            <Sun className="h-5 w-5 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" aria-hidden />
            <Moon className="absolute h-5 w-5 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" aria-hidden />
          </button>
          <Notifications />
          <UserMenu />
        </div>
      </div>
    </header>
  );
}
