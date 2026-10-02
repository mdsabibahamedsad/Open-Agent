'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => React.ReactNode;
  accessor?: (row: T) => React.ReactNode;
  sortable?: boolean;
  className?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  keyOf: (row: T, i: number) => string;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: React.ReactNode;
  page?: number;
  pageSize?: number;
  total?: number;
  onPageChange?: (page: number) => void;
  selectable?: boolean;
  selected?: Set<string>;
  onSelectionChange?: (s: Set<string>) => void;
}

export function DataTable<T>({
  columns, rows, keyOf, loading, error, onRetry,
  emptyTitle = 'No results', emptyDescription, emptyAction,
  page, pageSize, total, onPageChange,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = React.useState<string | null>(null);
  const [sortDir, setSortDir] = React.useState<1 | -1>(1);

  const sorted = React.useMemo(() => {
    if (!sortKey) return rows;
    const col = columns.find((c) => c.key === sortKey);
    if (!col) return rows;
    return [...rows].sort((a, b) => {
      const av = String(col.accessor?.(a) ?? '');
      const bv = String(col.accessor?.(b) ?? '');
      return av.localeCompare(bv) * sortDir;
    });
  }, [rows, sortKey, sortDir, columns]);

  if (loading) {
    return (
      <div className="overflow-hidden rounded-lg border" aria-busy="true" aria-label="Loading table">
        <div className="space-y-px bg-muted/40 p-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-10 animate-pulse rounded bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border p-8 text-center" role="alert">
        <p className="font-medium">Failed to load</p>
        <p className="mt-1 text-sm text-muted-foreground">{error}</p>
        {onRetry && (
          <button onClick={onRetry} className="mt-4 rounded-md border border-input px-4 py-2 text-sm hover:bg-accent">
            Retry
          </button>
        )}
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="rounded-lg border px-6 py-12 text-center">
        <h3 className="font-medium">{emptyTitle}</h3>
        {emptyDescription && <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{emptyDescription}</p>}
        {emptyAction && <div className="mt-4">{emptyAction}</div>}
      </div>
    );
  }

  const totalPages = page && pageSize && total !== undefined ? Math.max(1, Math.ceil(total / pageSize)) : null;

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left">
            <tr>
              {columns.map((c) => (
                <th key={c.key} scope="col" className={cn('px-4 py-2.5 font-medium text-muted-foreground', c.className)}>
                  {c.sortable ? (
                    <button
                      onClick={() => {
                        if (sortKey === c.key) setSortDir((d) => (d === 1 ? -1 : 1));
                        else {
                          setSortKey(c.key);
                          setSortDir(1);
                        }
                      }}
                      className="inline-flex items-center gap-1 hover:text-foreground"
                      aria-label={`Sort by ${c.header}`}
                    >
                      {c.header}
                      <span aria-hidden className="text-xs">{sortKey === c.key ? (sortDir === 1 ? '↑' : '↓') : ''}</span>
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y">
            {sorted.map((row, i) => (
              <tr key={keyOf(row, i)} className="hover:bg-muted/40">
                {columns.map((c) => (
                  <td key={c.key} className={cn('px-4 py-2.5', c.className)}>
                    {c.render ? c.render(row) : c.accessor?.(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages !== null && page !== undefined && onPageChange && (
        <nav className="flex items-center justify-end gap-1 text-sm" aria-label="Pagination">
          <button disabled={page <= 1} onClick={() => onPageChange(1)} aria-label="First page" className="rounded p-2 hover:bg-accent disabled:opacity-40">
            <ChevronsLeft className="h-4 w-4" />
          </button>
          <button disabled={page <= 1} onClick={() => onPageChange(page - 1)} aria-label="Previous page" className="rounded p-2 hover:bg-accent disabled:opacity-40">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="px-2 text-muted-foreground" aria-current="page">Page {page} of {totalPages}</span>
          <button disabled={page >= totalPages} onClick={() => onPageChange(page + 1)} aria-label="Next page" className="rounded p-2 hover:bg-accent disabled:opacity-40">
            <ChevronRight className="h-4 w-4" />
          </button>
          <button disabled={page >= totalPages} onClick={() => onPageChange(totalPages)} aria-label="Last page" className="rounded p-2 hover:bg-accent disabled:opacity-40">
            <ChevronsRight className="h-4 w-4" />
          </button>
        </nav>
      )}
    </div>
  );
}
