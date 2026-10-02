'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import {
  LayoutDashboard,
  Bot,
  GitBranch,
  Play,
  Wrench,
  Plug,
  Brain,
  Code2,
  Container,
  Store,
  Settings,
  ShieldCheck,
  ChevronLeft,
  ChevronRight,
  FileStack,
  BookOpen,
  Server,
  Sparkles,
  SlidersHorizontal,
  Building2,
} from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { useFeature } from '@/lib/feature-flags';

const primaryNav = [
  { name: 'Dashboard', href: '/', icon: LayoutDashboard, exact: true },
  { name: 'Agents', href: '/agents', icon: Bot },
  { name: 'Orchestrations', href: '/orchestrations', icon: Play },
  { name: 'Management', href: '/management', icon: ShieldCheck },
  { name: 'Workflows', href: '/workflows', icon: GitBranch },
  { name: 'Runs', href: '/runs', icon: Play },
  { name: 'Tools', href: '/tools', icon: Wrench },
  { name: 'MCP Servers', href: '/mcp', icon: Server },
  { name: 'Integrations', href: '/integrations', icon: Plug },
  { name: 'Memory', href: '/memory', icon: Brain },
  { name: 'Code', href: '/code', icon: Code2 },
  { name: 'Sandbox', href: '/sandbox', icon: Container },
  { name: 'Marketplace', href: '/marketplace', icon: Store },
];

const developerNav = [
  { name: 'Overview', href: '/developer', icon: Code2, exact: true },
  { name: 'Projects', href: '/developer/projects', icon: Building2 },
  { name: 'Extensions', href: '/developer/extensions', icon: Plug },
  { name: 'New Extension', href: '/developer/extensions/new', icon: Sparkles },
  { name: 'SDK', href: '/developer/sdk', icon: Code2 },
  { name: 'CLI', href: '/developer/cli', icon: SlidersHorizontal },
  { name: 'API Explorer', href: '/developer/api', icon: FileStack },
  { name: 'Docs', href: '/developer/docs', icon: BookOpen },
  { name: 'Registry', href: '/developer/registry', icon: Container },
  { name: 'Webhooks & Usage', href: '/developer/settings', icon: Settings },
];

const secondaryNav = [
  { name: 'Templates', href: '/templates', icon: FileStack },
  { name: 'Skills', href: '/skills', icon: Sparkles },
  { name: 'Presets', href: '/presets', icon: SlidersHorizontal },
  { name: 'Publisher Studio', href: '/publisher/packages', icon: Building2 },
  { name: 'Documentation', href: '/docs', icon: BookOpen },
  { name: 'Settings', href: '/settings', icon: Settings },
];

interface SidebarProps {
  collapsed?: boolean;
  onToggle?: () => void;
  mobile?: boolean;
}

export function Sidebar({ collapsed = false, onToggle, mobile = false }: SidebarProps) {
  const pathname = usePathname();
  const { user } = useAuth();
  const marketplaceOn = useFeature('marketplace');
  const isPlatform = !!(user?.is_platform_owner || user?.is_superadmin);

  const isActive = (href: string, exact?: boolean) =>
    exact ? pathname === href : pathname === href || pathname.startsWith(href + '/');

  const renderLink = (item: { name: string; href: string; icon: React.ElementType; exact?: boolean }) => {
    if (item.name === 'Marketplace' && !marketplaceOn) return null;
    const active = isActive(item.href, item.exact);
    return (
      <Link
        key={item.name}
        href={item.href}
        aria-current={active ? 'page' : undefined}
        title={collapsed && !mobile ? item.name : undefined}
        className={cn(
          'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          active
            ? 'bg-primary text-primary-foreground'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground',
          collapsed && !mobile && 'justify-center px-2',
        )}
      >
        <item.icon className="h-5 w-5 shrink-0" aria-hidden />
        {(!collapsed || mobile) && <span>{item.name}</span>}
      </Link>
    );
  };

  return (
    <aside
      aria-label="Main navigation"
      className={cn(
        'flex h-screen flex-col border-r bg-sidebar transition-all duration-200',
        mobile ? 'w-64' : collapsed ? 'w-16' : 'w-64',
        !mobile && 'fixed left-0 top-0 z-40 hidden lg:flex',
        mobile && 'fixed left-0 top-0 z-50 lg:hidden',
      )}
    >
      <div className="flex h-16 items-center justify-between border-b border-sidebar-border px-4">
        {(!collapsed || mobile) && (
          <Link href="/" className="flex items-center gap-2 text-lg font-semibold" aria-label="OpenAgent home">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Bot className="h-4 w-4" aria-hidden />
            </span>
            <span>OpenAgent</span>
          </Link>
        )}
        {onToggle && (
          <button
            onClick={onToggle}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            className={cn(
              'rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-foreground',
              collapsed && !mobile && 'mx-auto',
            )}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </button>
        )}
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto p-3" aria-label="Primary">
        {primaryNav.map(renderLink)}
        {(!collapsed || mobile) && (
          <p className="px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Developer
          </p>
        )}
        <div role="group" aria-label="Developer">
          {developerNav.map(renderLink)}
        </div>
        {isPlatform && (
          <Link
            href="/platform"
            aria-current={isActive('/platform') ? 'page' : undefined}
            title={collapsed && !mobile ? 'Platform' : undefined}
            className={cn(
              'mt-1 flex items-center gap-3 rounded-lg border border-dashed px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
              collapsed && !mobile && 'justify-center px-2',
            )}
          >
            <ShieldCheck className="h-5 w-5 shrink-0" aria-hidden />
            {(!collapsed || mobile) && <span>Platform</span>}
          </Link>
        )}
        {isPlatform && (!collapsed || mobile) && (
          <Link
            href="/master/marketplace"
            aria-current={isActive('/master/marketplace') ? 'page' : undefined}
            className="mt-1 flex items-center gap-3 rounded-lg px-3 py-2 pl-11 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <span>Marketplace moderation</span>
          </Link>
        )}
      </nav>

      <nav className="space-y-1 border-t border-sidebar-border p-3" aria-label="Secondary">
        {secondaryNav.map(renderLink)}
      </nav>

      <div className="border-t border-sidebar-border p-3">
        {(!collapsed || mobile) ? (
          <p className="text-center text-[11px] text-muted-foreground">OpenAgent v0.1.0 · Ctrl+K for commands</p>
        ) : (
          <p className="text-center text-[11px] text-muted-foreground" aria-hidden>v0.1</p>
        )}
      </div>
    </aside>
  );
}
