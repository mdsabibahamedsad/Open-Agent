'use client';

import * as React from 'react';
import type { WorkflowDefinition } from '@/features/workflows/types';
import { NODE_W, NODE_H, TRIGGER_H } from './WorkflowCanvas';

const MM_W = 168;
const MM_H = 112;

/** Viewport minimap: scaled content, viewport rect, click/drag to navigate. */
export function WorkflowMinimap({
  definition,
  visible,
  onNavigate,
}: {
  definition: WorkflowDefinition;
  /** Currently visible world rect (from the canvas). */
  visible: { x: number; y: number; w: number; h: number };
  onNavigate: (worldCenter: { x: number; y: number }) => void;
}) {
  const ref = React.useRef<HTMLDivElement>(null);

  const items = React.useMemo(() => {
    const list: { id: string; x: number; y: number; w: number; h: number; trigger: boolean }[] = [];
    for (const t of definition.triggers) {
      const p = t.position ?? { x: 80, y: 80 };
      list.push({ id: t.id, x: p.x, y: p.y, w: NODE_W, h: TRIGGER_H, trigger: true });
    }
    for (const n of definition.nodes) {
      const p = n.position ?? { x: 80, y: 80 };
      list.push({ id: n.id, x: p.x, y: p.y, w: NODE_W, h: NODE_H, trigger: false });
    }
    return list;
  }, [definition]);

  const { scale, ox, oy } = React.useMemo(() => {
    const box = ref.current?.getBoundingClientRect();
    const W = box?.width ?? MM_W;
    const H = box?.height ?? MM_H;
    if (items.length === 0) return { scale: 1, ox: 0, oy: 0 };
    const minX = Math.min(...items.map((i) => i.x)) - 40;
    const minY = Math.min(...items.map((i) => i.y)) - 40;
    const maxX = Math.max(...items.map((i) => i.x + i.w)) + 40;
    const maxY = Math.max(...items.map((i) => i.y + i.h)) + 40;
    const s = Math.min(W / Math.max(1, maxX - minX), H / Math.max(1, maxY - minY));
    return { scale: s, ox: -minX * s, oy: -minY * s };
  }, [items]);

  const toWorld = (clientX: number, clientY: number) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return { x: (clientX - rect.left - ox) / scale, y: (clientY - rect.top - oy) / scale };
  };

  const dragging = React.useRef(false);

  return (
    <div
      ref={ref}
      role="application"
      aria-label="Minimap. Activate to center the canvas on a point."
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onNavigate({ x: 400, y: 300 });
        }
      }}
      onPointerDown={(e) => {
        dragging.current = true;
        (e.currentTarget as Element).setPointerCapture(e.pointerId);
        onNavigate(toWorld(e.clientX, e.clientY));
      }}
      onPointerMove={(e) => {
        if (dragging.current) onNavigate(toWorld(e.clientX, e.clientY));
      }}
      onPointerUp={() => {
        dragging.current = false;
      }}
      className="h-28 cursor-crosshair overflow-hidden rounded-md border bg-card/95 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      style={{ width: MM_W, height: MM_H }}
    >
      <svg width="100%" height="100%" aria-hidden>
        {items.map((i) => (
          <rect
            key={i.id}
            x={i.x * scale + ox}
            y={i.y * scale + oy}
            width={Math.max(2, i.w * scale)}
            height={Math.max(2, i.h * scale)}
            rx={1.5}
            className={i.trigger ? 'fill-amber-500/70' : 'fill-primary/60'}
          />
        ))}
        {/* viewport indicator */}
        <rect
          x={visible.x * scale + ox}
          y={visible.y * scale + oy}
          width={visible.w * scale}
          height={visible.h * scale}
          fill="none"
          strokeWidth={1.5}
          className="stroke-foreground/60"
          rx={2}
        />
      </svg>
    </div>
  );
}
