'use client';

import { ReactNode } from 'react';
import { QueryProvider } from '@/lib/query-provider';
import { ThemeProvider } from 'next-themes';
import { AuthProvider } from '@/context/AuthContext';
import { OrganizationProvider } from '@/context/OrganizationContext';
import { FeatureFlagProvider } from '@/lib/feature-flags';
import { ToastProvider } from '@/components/ui/toast';

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryProvider>
        <AuthProvider>
          <OrganizationProvider>
            <FeatureFlagProvider>
              <ToastProvider>{children}</ToastProvider>
            </FeatureFlagProvider>
          </OrganizationProvider>
        </AuthProvider>
      </QueryProvider>
    </ThemeProvider>
  );
}
