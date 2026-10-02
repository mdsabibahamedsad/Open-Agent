'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

interface AvatarProps extends React.HTMLAttributes<HTMLDivElement> {
  src?: string;
  alt?: string;
  fallback?: string;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}

const sizeClasses = {
  sm: 'h-8 w-8 text-xs',
  md: 'h-10 w-10 text-sm',
  lg: 'h-12 w-12 text-base',
  xl: 'h-16 w-16 text-lg',
};

function getInitials(name: string): string {
  return name
    .split(' ')
    .map((part) => part[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
}

export function Avatar({ src, alt, fallback, size = 'md', className, ...props }: AvatarProps) {
  const [error, setError] = React.useState(false);

  if (src && !error) {
    return (
      <div className={cn('relative inline-flex shrink-0 overflow-hidden rounded-full', sizeClasses[size], className)} {...props}>
        <img src={src} alt={alt || ''} className="aspect-square h-full w-full object-cover" onError={() => setError(true)} />
      </div>
    );
  }

  return (
    <div
      className={cn(
        'inline-flex items-center justify-center font-medium rounded-full bg-muted',
        sizeClasses[size],
        className
      )}
      {...props}
    >
      {fallback || (alt ? getInitials(alt) : '?')}
    </div>
  );
}

export function AvatarGroup({ children, className, max = 5, ...props }: React.HTMLAttributes<HTMLDivElement> & { max?: number }) {
  const kids = React.Children.toArray(children);
  const visible = kids.slice(0, max);
  const remaining = kids.length - max;

  return (
    <div className={cn('flex -space-x-2', className)} {...props}>
      {visible.map((child, index) =>
        React.cloneElement(child as React.ReactElement, { key: index, className: 'ring-2 ring-background' })
      )}
      {remaining > 0 && (
        <div className={cn('flex items-center justify-center font-medium rounded-full bg-muted', sizeClasses.md, 'ring-2 ring-background')}>
          +{remaining}
        </div>
      )}
    </div>
  );
}