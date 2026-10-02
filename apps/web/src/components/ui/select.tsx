'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

// Minimal accessible Select with a Radix-style API, backed by a native
// <select> (no extra dependency). Controlled via value/onValueChange.

interface SelectContextValue {
  value: string;
  onValueChange: (v: string) => void;
  placeholder?: string;
  items: { value: string; label: React.ReactNode }[];
  register: (value: string, label: React.ReactNode) => void;
}

const SelectContext = React.createContext<SelectContextValue | null>(null);

export function Select({
  value,
  onValueChange,
  children,
  placeholder,
}: {
  value?: string;
  onValueChange?: (v: string) => void;
  children: React.ReactNode;
  placeholder?: string;
}) {
  const [items, setItems] = React.useState<{ value: string; label: React.ReactNode }[]>([]);
  const register = React.useCallback((v: string, label: React.ReactNode) => {
    setItems((prev) => (prev.some((i) => i.value === v) ? prev : [...prev, { value: v, label }]));
  }, []);
  return (
    <SelectContext.Provider value={{ value: value ?? '', onValueChange: onValueChange ?? (() => {}), placeholder, items, register }}>
      <span className="inline-flex flex-col gap-1">{children}</span>
    </SelectContext.Provider>
  );
}

export function SelectTrigger({ children, className }: { children?: React.ReactNode; className?: string }) {
  const ctx = React.useContext(SelectContext);
  if (!ctx) return <>{children}</>;
  return (
    <select
      aria-label={ctx.placeholder ?? 'Select option'}
      className={cn('rounded-md border border-input bg-background px-3 py-2 text-sm', className)}
      value={ctx.value}
      onChange={(e) => ctx.onValueChange(e.target.value)}
    >
      {ctx.placeholder && ctx.value === '' && <option value="">{ctx.placeholder}</option>}
      {ctx.items.map((item) => (
        <option key={item.value} value={item.value}>
          {typeof item.label === 'string' ? item.label : item.value}
        </option>
      ))}
      {children}
    </select>
  );
}

export function SelectValue({ placeholder }: { placeholder?: string }) {
  const ctx = React.useContext(SelectContext);
  // Placeholder is rendered by the trigger; keep API-compatible.
  void ctx;
  void placeholder;
  return null;
}

export function SelectContent({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

export function SelectItem({ value, children }: { value: string; children: React.ReactNode }) {
  const ctx = React.useContext(SelectContext);
  React.useEffect(() => {
    ctx?.register(value, children);
  }, [ctx, value, children]);
  // Options are rendered by the trigger from registered items.
  return null;
}
