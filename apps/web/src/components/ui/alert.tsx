'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

type AlertVariant = 'default' | 'destructive' | 'success' | 'warning';

export function Alert({
  variant = 'default',
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { variant?: AlertVariant }) {
  const styles: Record<AlertVariant, string> = {
    default: 'border-border bg-card text-card-foreground',
    destructive: 'border-destructive/30 bg-destructive/10 text-destructive [&_p]:text-destructive',
    success: 'border-emerald-500/30 bg-emerald-500/10 [&_p]:text-emerald-700 dark:[&_p]:text-emerald-300',
    warning: 'border-amber-500/30 bg-amber-500/10 [&_p]:text-amber-700 dark:[&_p]:text-amber-300',
  };
  return <div role="alert" className={cn('rounded-lg border p-4 text-sm', styles[variant], className)} {...props} />;
}

export function AlertTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h5 className={cn('mb-1 font-medium leading-none tracking-tight', className)} {...props} />;
}

export function AlertDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn('text-sm text-muted-foreground', className)} {...props} />;
}
