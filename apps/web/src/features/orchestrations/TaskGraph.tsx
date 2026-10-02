'use client';

import * as React from 'react';
import { groupByDepth, statusColor } from './graph';
import type { OrchestrationTask } from './types';

interface GraphNode {
  id: string;
  label: string;
  status: string;
  depth: number;
  index: number;
}

export function TaskGraph({
  tasks,
  selectedId,
  onSelect,
}: {
  tasks: OrchestrationTask[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
}) {
  const [zoom, setZoom] = React.useState(1);
  const [pan, setPan] = React.useState({ x: 0, y: 0 });
  const dragRef = React.useRef<{ x: number; y: number; px: number; py: number } | null>(null);

  const levels = React.useMemo(() => groupByDepth(tasks), [tasks]);

  const nodes: GraphNode[] = React.useMemo(() => {
    const out: GraphNode[] = [];
    levels.forEach(([depth, group]) => {
      group.forEach((t, index) => {
        out.push({ id: t.id, label: t.title, status: t.status, depth, index });
      });
    });
    return out;
  }, [levels]);

  const pos = (n: GraphNode) => ({
    x: 120 + (n.depth - 1) * 220,
    y: 60 + n.index * 90,
  });

  const width = Math.max(600, levels.length * 220 + 120);
  const height = Math.max(
    320,
    Math.max(...levels.map(([, g]) => g.length), 1) * 90 + 80,
  );

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setZoom((z) => Math.min(2.5, Math.max(0.4, z + (e.deltaY < 0 ? 0.1 : -0.1))));
  };

  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex items-center gap-2 border-b bg-muted/40 px-3 py-2 text-xs">
        <button
          type="button"
          className="rounded border px-2 py-1"
          onClick={() => setZoom((z) => Math.min(2.5, z + 0.1))}
          aria-label="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          className="rounded border px-2 py-1"
          onClick={() => setZoom((z) => Math.max(0.4, z - 0.1))}
          aria-label="Zoom out"
        >
          −
        </button>
        <button
          type="button"
          className="rounded border px-2 py-1"
          onClick={() => {
            setZoom(1);
            setPan({ x: 0, y: 0 });
          }}
        >
          Reset
        </button>
        <span className="text-muted-foreground">{Math.round(zoom * 100)}%</span>
      </div>
      <div
        className="cursor-grab overflow-auto bg-background active:cursor-grabbing"
        style={{ maxHeight: 520 }}
        onWheel={onWheel}
        onMouseDown={(e) => {
          dragRef.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y };
        }}
        onMouseMove={(e) => {
          if (!dragRef.current) return;
          setPan({
            x: dragRef.current.px + (e.clientX - dragRef.current.x),
            y: dragRef.current.py + (e.clientY - dragRef.current.y),
          });
        }}
        onMouseUp={() => {
          dragRef.current = null;
        }}
        onMouseLeave={() => {
          dragRef.current = null;
        }}
      >
        <svg
          width={width * zoom}
          height={height * zoom}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Task dependency graph"
        >
          <g transform={`translate(${pan.x},${pan.y}) scale(${zoom})`}>
            {nodes.map((n) => {
              const p = pos(n);
              const color = statusColor(n.status);
              const selected = selectedId === n.id;
              return (
                <g
                  key={n.id}
                  transform={`translate(${p.x},${p.y})`}
                  onClick={() => onSelect?.(n.id)}
                  style={{ cursor: onSelect ? 'pointer' : 'default' }}
                >
                  <rect
                    x={-90}
                    y={-26}
                    width={180}
                    height={52}
                    rx={8}
                    fill="var(--background, #fff)"
                    stroke={selected ? '#2563eb' : color}
                    strokeWidth={selected ? 3 : 2}
                  />
                  <circle cx={-78} cy={0} r={6} fill={color} />
                  <text x={-64} y={-2} fontSize={12} fontWeight={600} fill="currentColor">
                    {n.label.length > 22 ? `${n.label.slice(0, 22)}…` : n.label}
                  </text>
                  <text x={-64} y={14} fontSize={10} fill={color}>
                    {n.status}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
    </div>
  );
}
