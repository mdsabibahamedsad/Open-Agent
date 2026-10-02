'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import { PageLoading } from '@/components/ui/loading';

export function Protected({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  React.useEffect(() => {
    if (status === 'unauthenticated') router.replace('/login');
  }, [status, router]);

  if (status === 'loading') return <PageLoading label="Checking session…" />;
  if (status === 'unauthenticated') return <PageLoading label="Redirecting to sign in…" />;
  return <>{children}</>;
}
