'use client';

import * as React from 'react';
import { nodeMeta, outputPortsFor, triggerMeta } from '@/features/workflows/node-catalog';
import type { WorkflowEditor } from '@/features/workflows/use-workflow-editor';
import { WorkflowMinimap } from './WorkflowMinimap';
import { CanvasContextMenu, type MenuTarget } from './CanvasContextMenu';
import { cn } from '@/lib/utils';
import { Minus, Plus, Maximize, MousePointer2, StickyNote } from 'lucide-react';

// Custom SVG canvas (no external graph dependency):
// pan, zoom, drag (single + multi), box select, edge creation,
// context menu, minimap, copy/paste/duplicate, keyboard ops.

export const NODE_W = 208;
export const NODE_H = 104;
export const TRIGGER_H = 88;

export interface Viewport {
  x: number;
  y: number;
  k: number;
}

function portPosition(
  kind: 'trigger' | 'node',
  pos: { x: number; y: number },
  port: 'in' | string,
  outputs: string[],
): { x: number; y: number } {
  if (port === 'in') return { x: pos.x + NODE_W / 2, y: pos.y };
  const idx = Math.max(0, outputs.indexOf(port));
  const n = outputs.length;
  const slot = NODE_W / (n + 1);
  const h = kind === 'trigger' ? TRIGGER_H : NODE_H;
  return { x: pos.x + slot * (idx + 1), y: pos.y + h };
}

function edgePath(a: { x: number; y: number }, b: { x: number; y: number }): string {
  const dy = Math.max(40, Math.abs(b.y - a.y) / 2);
  return `M ${a.x} ${a.y} C ${a.x} ${a.y + dy}, ${b.x} ${b.y - dy}, ${b.x} ${b.y}`;
}

interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export function WorkflowCanvas({ editor, readOnly = false }: { editor: WorkflowEditor; readOnly?: boolean }) {
  const { definition, selection, selectedIds, select, validation } = editor;
  const svgRef = React.useRef<SVGSVGElement>(null);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const [view, setView] = React.useState<Viewport>({ x: 40, y: 40, k: 1 });
  const [size, setSize] = React.useState({ w: 800, h: 560 });
  const [cursor, setCursor] = React.useState<{ x: number; y: number } | null>(null);
  const [box, setBox] = React.useState<Box | null>(null);
  const [menu, setMenu] = React.useState<{ x: number; y: number; target: MenuTarget } | null>(null);
  const dragRef = React.useRef<{ ids: string[]; startX: number; startY: number; before: typeof definition } | null>(null);
  const panRef = React.useRef<{ sx: number; sy: number; vx: number; vy: number } | null>(null);
  const boxRef = React.useRef<{ sx: number; sy: number } | null>(null);

  React.useEffect(() => {
    const measure = () => {
      const r = containerRef.current?.getBoundingClientRect();
      if (r) setSize({ w: r.width, h: r.height });
    };
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, []);

  const errorIds = React.useMemo(
    () => new Set(validation.errors.map((e) => e.node_id).filter(Boolean) as string[]),
    [validation],
  );

  const kindOf = React.useCallback(
    (id: string): 'trigger' | 'node' | 'edge' => {
      if (definition.triggers.some((t) => t.id === id)) return 'trigger';
      if (definition.nodes.some((n) => n.id === id)) return 'node';
      return 'edge';
    },
    [definition],
  );

  const posOf = React.useCallback(
    (id: string) => {
      const t = definition.triggers.find((x) => x.id === id);
      if (t) return t.position ?? { x: 80, y: 80 };
      const n = definition.nodes.find((x) => x.id === id);
      return n?.position ?? { x: 80, y: 80 };
    },
    [definition],
  );

  const outputsOf = React.useCallback(
    (id: string): { kind: 'trigger' | 'node'; outputs: string[] } => {
      const t = definition.triggers.find((x) => x.id === id);
      if (t) return { kind: 'trigger', outputs: ['out'] };
      const n = definition.nodes.find((x) => x.id === id);
      if (n) {
        try {
          return { kind: 'node', outputs: outputPortsFor(nodeMeta(n.type), n) };
        } catch {
          return { kind: 'node', outputs: ['out'] };
        }
      }
      return { kind: 'node', outputs: ['out'] };
    },
    [definition],
  );

  const toWorld = React.useCallback(
    (clientX: number, clientY: number) => {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return { x: 0, y: 0 };
      return {
        x: (clientX - rect.left - view.x) / view.k,
        y: (clientY - rect.top - view.y) / view.k,
      };
    },
    [view],
  );

  // -- background: pan (drag) or box select (shift+drag) -----------------------
  const onBackgroundDown = (e: React.PointerEvent) => {
    if (readOnly) return;
    if (e.shiftKey) {
      boxRef.current = { sx: e.clientX, sy: e.clientY };
      const w = toWorld(e.clientX, e.clientY);
      setBox({ x0: w.x, y0: w.y, x1: w.x, y1: w.y });
      return;
    }
    panRef.current = { sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y };
    select(null);
    editor.setPendingEdge(null);
  };

  const onBackgroundMove = (e: React.PointerEvent) => {
    if (panRef.current) {
      setView((v) => ({
        ...v,
        x: panRef.current!.vx + (e.clientX - panRef.current!.sx),
        y: panRef.current!.vy + (e.clientY - panRef.current!.sy),
      }));
    }
    if (boxRef.current) {
      const w = toWorld(e.clientX, e.clientY);
      setBox((b) => (b ? { ...b, x1: w.x, y1: w.y } : b));
    }
    if (svgRef.current) {
      const rect = svgRef.current.getBoundingClientRect();
      setCursor({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    }
  };

  const onBackgroundUp = (e: React.PointerEvent) => {
    panRef.current = null;
    if (boxRef.current && box) {
      const x0 = Math.min(box.x0, box.x1);
      const x1 = Math.max(box.x0, box.x1);
      const y0 = Math.min(box.y0, box.y1);
      const y1 = Math.max(box.y0, box.y1);
      if (Math.abs(x1 - x0) > 8 / view.k || Math.abs(y1 - y0) > 8 / view.k) {
        const hits: string[] = [];
        for (const t of definition.triggers) {
          const p = t.position ?? { x: 80, y: 80 };
          if (p.x < x1 && p.x + NODE_W > x0 && p.y < y1 && p.y + TRIGGER_H > y0) hits.push(t.id);
        }
        for (const n of definition.nodes) {
          const p = n.position ?? { x: 80, y: 80 };
          if (p.x < x1 && p.x + NODE_W > x0 && p.y < y1 && p.y + NODE_H > y0) hits.push(n.id);
        }
        editor.boxSelect(hits);
      } else if (!e.shiftKey) {
        select(null);
      }
    }
    boxRef.current = null;
    setBox(null);
  };

  const onWheelNative = React.useCallback((e: WheelEvent) => {
    if (readOnlyRef.current) return;
    e.preventDefault();
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    setView((v) => {
      const k = Math.min(2, Math.max(0.25, v.k * factor));
      const wx = (mx - v.x) / v.k;
      const wy = (my - v.y) / v.k;
      return { k, x: mx - wx * k, y: my - wy * k };
    });
  }, []);

  const readOnlyRef = React.useRef(readOnly);
  readOnlyRef.current = readOnly;

  React.useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    el.addEventListener('wheel', onWheelNative, { passive: false });
    return () => el.removeEventListener('wheel', onWheelNative);
  }, [onWheelNative]);

  // -- node drag (single + multi) ------------------------------------------------
  const onItemDown = (e: React.PointerEvent, id: string) => {
    if (readOnly) return;
    e.stopPropagation();
    const kind = kindOf(id);
    if (e.ctrlKey || e.metaKey) {
      editor.toggleSelect({ kind: kind === 'edge' ? 'node' : kind, id });
      return;
    }
    let ids = selectedIds.includes(id) ? selectedIds.filter((x) => kindOf(x) !== 'edge') : [id];
    if (ids.length === 0) ids = [id];
    if (!selectedIds.includes(id)) {
      select(kind === 'edge' ? { kind: 'node', id } : { kind, id });
    }
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    dragRef.current = { ids, startX: e.clientX, startY: e.clientY, before: editor.definition };
  };

  const onItemMove = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    const dx = (e.clientX - drag.startX) / view.k;
    const dy = (e.clientY - drag.startY) / view.k;
    const snap = (v: number) => Math.round(v / 4) * 4;
    for (const id of drag.ids) {
      const base =
        drag.before.triggers.find((t) => t.id === id)?.position ??
        drag.before.nodes.find((n) => n.id === id)?.position ??
        posOf(id);
      editor.dispatch({
        type: 'move-item',
        id,
        x: Math.max(0, snap(base.x + dx)),
        y: Math.max(0, snap(base.y + dy)),
      });
    }
  };

  const onItemUp = () => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (drag) editor.dispatch({ type: 'commit-move', before: drag.before });
  };

  // -- edge creation ----------------------------------------------------------
  const onOutputDown = (e: React.PointerEvent, fromId: string, port: string) => {
    if (readOnly) return;
    e.stopPropagation();
    editor.setPendingEdge({ fromId, fromPort: port });
  };
  const onInputUp = (e: React.PointerEvent, toId: string) => {
    if (readOnly) return;
    e.stopPropagation();
    const pending = editor.pendingEdge;
    if (pending && pending.fromId !== toId) {
      editor.connect(pending.fromId, toId, pending.fromPort);
    }
    editor.setPendingEdge(null);
  };

  // -- drop from palette ------------------------------------------------------
  const onDrop = (e: React.DragEvent) => {
    if (readOnly) return;
    e.preventDefault();
    const payload = e.dataTransfer.getData('application/x-openagent-node');
    if (!payload) return;
    try {
      const { kind, nodeType } = JSON.parse(payload) as { kind: string; nodeType: string };
      const w = toWorld(e.clientX, e.clientY);
      const at = { x: Math.max(0, Math.round(w.x - NODE_W / 2)), y: Math.max(0, Math.round(w.y - 30)) };
      if (kind === 'trigger') editor.addTrigger(nodeType as never, at);
      else editor.addNode(nodeType as never, at);
    } catch {
      // Invalid payload — ignore.
    }
  };

  // -- context menu -------------------------------------------------------------
  const onContextMenu = (e: React.MouseEvent) => {
    if (readOnly) return;
    e.preventDefault();
    const el = (e.target as Element).closest?.('[data-item-kind]') as Element | null;
    if (el) {
      const kind = el.getAttribute('data-item-kind') as 'trigger' | 'node' | 'edge';
      const id = el.getAttribute('data-item-id')!;
      const node = definition.nodes.find((n) => n.id === id);
      if (!selectedIds.includes(id)) select({ kind, id });
      setMenu({ x: e.clientX, y: e.clientY, target: { kind, id, disabled: node?.disabled } });
    } else {
      setMenu({ x: e.clientX, y: e.clientY, target: { kind: 'background' } });
    }
  };

  const onMenuAction = (actionId: string, target: MenuTarget) => {
    if (readOnly) return;
    switch (actionId) {
      case 'configure':
        if (target.id) select({ kind: target.kind as 'trigger' | 'node' | 'edge', id: target.id });
        break;
      case 'duplicate':
        if (target.id) {
          editor.boxSelect([target.id]);
          editor.duplicateSelection();
        }
        break;
      case 'copy':
        if (target.id) {
          editor.boxSelect([target.id]);
          editor.copySelection();
        }
        break;
      case 'paste':
        editor.pasteClipboard();
        break;
      case 'disable':
        if (target.id && target.kind === 'node') {
          editor.dispatch({ type: 'update-node', id: target.id, patch: { disabled: true } });
        }
        break;
      case 'enable':
        if (target.id && target.kind === 'node') {
          editor.dispatch({ type: 'update-node', id: target.id, patch: { disabled: false } });
        }
        break;
      case 'note':
        if (target.id) select({ kind: target.kind as 'trigger' | 'node', id: target.id });
        break;
      case 'delete':
        if (target.id) editor.dispatch({ type: 'delete-ids', ids: [target.id] });
        break;
      case 'fit':
        fitView();
        break;
      default:
        break;
    }
  };

  // -- keyboard -----------------------------------------------------------------
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (readOnly) return;
    const el = document.activeElement;
    const typing = el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT');
    if (typing) return;
    const mod = e.ctrlKey || e.metaKey;
    if ((e.key === 'Delete' || e.key === 'Backspace') && (selection || selectedIds.length > 0)) {
      e.preventDefault();
      editor.dispatch({ type: 'delete-selection' });
    } else if (e.key === 'Escape') {
      editor.setPendingEdge(null);
      select(null);
      setMenu(null);
    } else if (mod && e.key.toLowerCase() === 'z' && !e.shiftKey) {
      e.preventDefault();
      editor.undo();
    } else if (mod && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) {
      e.preventDefault();
      editor.redo();
    } else if (mod && e.key.toLowerCase() === 'c' && selectedIds.length > 0) {
      e.preventDefault();
      editor.copySelection();
    } else if (mod && e.key.toLowerCase() === 'v') {
      e.preventDefault();
      editor.pasteClipboard();
    } else if (mod && e.key.toLowerCase() === 'd' && selectedIds.length > 0) {
      e.preventDefault();
      editor.duplicateSelection();
    } else if ((e.key === 'f' || e.key === 'F') && !mod) {
      e.preventDefault();
      fitView();
    } else if (selection && selection.kind !== 'edge' && e.key.startsWith('Arrow')) {
      e.preventDefault();
      const step = e.shiftKey ? 16 : 4;
      const ids = selectedIds.length > 0 ? selectedIds.filter((x) => kindOf(x) !== 'edge') : [selection.id];
      const before = editor.definition;
      for (const id of ids) {
        const p = posOf(id);
        const dx = e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0;
        const dy = e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0;
        editor.dispatch({ type: 'move-item', id, x: Math.max(0, p.x + dx), y: Math.max(0, p.y + dy) });
      }
      editor.dispatch({ type: 'commit-move', before });
    }
  };

  const fitView = () => {
    const items = [
      ...definition.triggers.map((t) => ({ p: t.position ?? { x: 80, y: 80 }, h: TRIGGER_H })),
      ...definition.nodes.map((n) => ({ p: n.position ?? { x: 80, y: 80 }, h: NODE_H })),
    ];
    if (items.length === 0) {
      setView({ x: 40, y: 40, k: 1 });
      return;
    }
    const W = size.w;
    const H = size.h;
    const minX = Math.min(...items.map((i) => i.p.x)) - 60;
    const minY = Math.min(...items.map((i) => i.p.y)) - 60;
    const maxX = Math.max(...items.map((i) => i.p.x + NODE_W)) + 60;
    const maxY = Math.max(...items.map((i) => i.p.y + i.h)) + 60;
    const k = Math.min(1.5, Math.max(0.25, Math.min(W / (maxX - minX), H / (maxY - minY))));
    setView({ k, x: (W - (maxX - minX) * k) / 2 - minX * k, y: (H - (maxY - minY) * k) / 2 - minY * k });
  };

  const centerOn = (world: { x: number; y: number }) => {
    setView((v) => ({ ...v, x: size.w / 2 - world.x * v.k, y: size.h / 2 - world.y * v.k }));
  };

  const pendingFrom = editor.pendingEdge ? posOf(editor.pendingEdge.fromId) : null;
  const visibleWorld = { x: -view.x / view.k, y: -view.y / view.k, w: size.w / view.k, h: size.h / view.k };

  const isSelected = (id: string) => selectedIds.includes(id);

  return (
    <div ref={containerRef} className="relative h-[560px] overflow-hidden rounded-lg border bg-background" onKeyDown={onKeyDown}>
      <svg
        ref={svgRef}
        role="application"
        aria-label="Workflow canvas. Drag nodes to move them. Shift-drag for box select. Drag from an output port to an input port to connect. Right-click for actions."
        tabIndex={0}
        className="h-full w-full touch-none select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onPointerDown={onBackgroundDown}
        onPointerMove={(e) => {
          onBackgroundMove(e);
          onItemMove(e);
        }}
        onPointerUp={(e) => {
          onBackgroundUp(e);
          onItemUp();
        }}
        onContextMenu={onContextMenu}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
      >
        <defs>
          <pattern id="oa-grid" width="24" height="24" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" className="fill-muted-foreground/30" />
          </pattern>
          <marker id="oa-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 1 L 9 5 L 0 9 z" className="fill-muted-foreground" />
          </marker>
          <marker id="oa-arrow-sel" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 1 L 9 5 L 0 9 z" className="fill-primary" />
          </marker>
        </defs>
        <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
          <rect x={-5000} y={-5000} width={10000} height={10000} fill="url(#oa-grid)" />

          {/* box selection */}
          {box && (
            <rect
              x={Math.min(box.x0, box.x1)}
              y={Math.min(box.y0, box.y1)}
              width={Math.abs(box.x1 - box.x0)}
              height={Math.abs(box.y1 - box.y0)}
              fill="none"
              strokeWidth={1.5 / view.k}
              strokeDasharray={`${6 / view.k} ${4 / view.k}`}
              className="stroke-primary fill-primary/5"
            />
          )}

          {/* edges */}
          {definition.edges.map((edge) => {
            const fromPos = posOf(edge.from);
            const { kind, outputs } = outputsOf(edge.from);
            const port = edge.label && outputs.includes(edge.label) ? edge.label : outputs[0] ?? 'out';
            const a = portPosition(kind, fromPos, port, outputs);
            const b = portPosition('node', posOf(edge.to), 'in', ['in']);
            const selected = isSelected(edge.id);
            return (
              <g key={edge.id} data-item-kind="edge" data-item-id={edge.id}>
                <path
                  d={edgePath(a, b)}
                  fill="none"
                  strokeWidth={selected ? 3 : 2}
                  markerEnd={selected ? 'url(#oa-arrow-sel)' : 'url(#oa-arrow)'}
                  className={selected ? 'stroke-primary' : 'stroke-muted-foreground'}
                />
                <path
                  d={edgePath(a, b)}
                  fill="none"
                  stroke="transparent"
                  strokeWidth={16}
                  className="cursor-pointer"
                  onPointerDown={(e) => {
                    if (readOnly) return;
                    e.stopPropagation();
                    if (e.ctrlKey || e.metaKey) editor.toggleSelect({ kind: 'edge', id: edge.id });
                    else select({ kind: 'edge', id: edge.id });
                  }}
                >
                  <title>{`Edge ${edge.from} to ${edge.to}${edge.label ? ` (${edge.label})` : ''}`}</title>
                </path>
                {edge.label && (
                  <text
                    x={(a.x + b.x) / 2}
                    y={(a.y + b.y) / 2 - 6}
                    textAnchor="middle"
                    fontSize={11}
                    className="fill-muted-foreground"
                  >
                    {edge.label}
                  </text>
                )}
              </g>
            );
          })}

          {/* pending edge */}
          {editor.pendingEdge && pendingFrom && cursor && (
            <path
              d={edgePath(
                portPosition(
                  outputsOf(editor.pendingEdge.fromId).kind,
                  pendingFrom,
                  editor.pendingEdge.fromPort,
                  ['out'],
                ),
                toWorld(cursor.x + (svgRef.current?.getBoundingClientRect().left ?? 0), cursor.y + (svgRef.current?.getBoundingClientRect().top ?? 0)),
              )}
              fill="none"
              strokeWidth={2}
              strokeDasharray="6 4"
              className="stroke-primary"
            />
          )}

          {/* triggers */}
          {definition.triggers.map((t) => {
            const meta = triggerMeta(t.type);
            const Icon = meta.icon;
            const p = t.position ?? { x: 80, y: 80 };
            const selected = isSelected(t.id);
            const hasError = errorIds.has(t.id);
            const out = portPosition('trigger', p, 'out', ['out']);
            return (
              <g
                key={t.id}
                transform={`translate(${p.x},${p.y})`}
                data-item-kind="trigger"
                data-item-id={t.id}
                tabIndex={readOnly ? undefined : 0}
                role={readOnly ? undefined : 'button'}
                aria-label={readOnly ? undefined : `Trigger ${t.name}. Press Enter to select.`}
                onKeyDown={(e) => {
                  if (!readOnly && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault();
                    select({ kind: 'trigger', id: t.id });
                  }
                }}
                onPointerDown={(e) => onItemDown(e, t.id)}
                className={readOnly ? '' : 'cursor-grab active:cursor-grabbing'}
              >
                <rect
                  width={NODE_W}
                  height={TRIGGER_H}
                  rx={10}
                  className={cn(
                    'fill-card stroke-2',
                    selected ? 'stroke-primary' : hasError ? 'stroke-destructive' : 'stroke-amber-500/60',
                  )}
                  strokeWidth={2}
                />
                <rect width={NODE_W} height={26} rx={10} className="fill-amber-500/15" />
                <rect y={16} width={NODE_W} height={10} className="fill-amber-500/15" />
                <Icon x={10} y={5} width={16} height={16} className="text-amber-600 dark:text-amber-400" />
                <text x={32} y={18} fontSize={11} fontWeight={700} className="fill-foreground">
                  ⚡ {t.type.toUpperCase()}
                </text>
                <text x={12} y={46} fontSize={13} fontWeight={600} className="fill-foreground">
                  {t.name.length > 26 ? `${t.name.slice(0, 25)}…` : t.name}
                </text>
                <text x={12} y={64} fontSize={11} className="fill-muted-foreground">
                  {t.id}
                </text>
                {hasError && (
                  <g transform={`translate(${NODE_W - 22},6)`}>
                    <circle r={9} className="fill-destructive" />
                    <text textAnchor="middle" dy={4} fontSize={12} fontWeight={800} fill="white">!</text>
                  </g>
                )}
                {!readOnly && (
                  <g
                    transform={`translate(${out.x - p.x},${out.y - p.y})`}
                    onPointerDown={(e) => onOutputDown(e, t.id, 'out')}
                    className="cursor-crosshair"
                  >
                    <circle r={10} fill="transparent" />
                    <circle r={5.5} className="fill-background stroke-primary" strokeWidth={2}>
                      <title>Drag to connect</title>
                    </circle>
                  </g>
                )}
              </g>
            );
          })}

          {/* nodes */}
          {definition.nodes.map((n) => {
            const meta = nodeMeta(n.type);
            const Icon = meta.icon;
            const p = n.position ?? { x: 80, y: 80 };
            const selected = isSelected(n.id);
            const hasError = errorIds.has(n.id);
            const inp = portPosition('node', p, 'in', ['in']);
            const ports = outputPortsFor(meta, n);
            return (
              <g
                key={n.id}
                transform={`translate(${p.x},${p.y})`}
                data-item-kind="node"
                data-item-id={n.id}
                tabIndex={readOnly ? undefined : 0}
                role={readOnly ? undefined : 'button'}
                aria-label={readOnly ? undefined : `Node ${n.name}, type ${meta.label}${n.disabled ? ', disabled' : ''}. Press Enter to select.`}
                onKeyDown={(e) => {
                  if (!readOnly && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault();
                    select({ kind: 'node', id: n.id });
                  }
                }}
                onPointerDown={(e) => onItemDown(e, n.id)}
                className={cn(readOnly ? '' : 'cursor-grab active:cursor-grabbing', n.disabled && 'opacity-50')}
              >
                <rect
                  width={NODE_W}
                  height={NODE_H}
                  rx={10}
                  className={cn('fill-card', selected ? 'stroke-primary' : hasError ? 'stroke-destructive' : 'stroke-border')}
                  strokeWidth={selected || hasError ? 2.5 : 1.5}
                  strokeDasharray={n.disabled ? '5 3' : undefined}
                />
                <Icon x={12} y={10} width={18} height={18} className="text-primary" />
                <text x={38} y={20} fontSize={10} fontWeight={700} className="fill-muted-foreground">
                  {meta.label.toUpperCase()}
                </text>
                <text x={12} y={50} fontSize={13.5} fontWeight={600} className="fill-foreground">
                  {n.name.length > 26 ? `${n.name.slice(0, 25)}…` : n.name}
                </text>
                <text x={12} y={68} fontSize={11} className="fill-muted-foreground">
                  {n.id}
                </text>
                {n.disabled && (
                  <text x={12} y={86} fontSize={10.5} fontWeight={700} className="fill-muted-foreground">
                    DISABLED
                  </text>
                )}
                {!n.disabled && n.approval_required && (
                  <text x={12} y={86} fontSize={10.5} className="fill-amber-600 dark:fill-amber-400">
                    requires approval
                  </text>
                )}
                {n.notes && (
                  <g transform={`translate(${NODE_W - 44},${NODE_H - 24})`} aria-label="Has a note">
                    <StickyNote width={15} height={15} className="text-muted-foreground" />
                  </g>
                )}
                {hasError && (
                  <g transform={`translate(${NODE_W - 22},6)`}>
                    <circle r={9} className="fill-destructive" />
                    <text textAnchor="middle" dy={4} fontSize={12} fontWeight={800} fill="white">!</text>
                  </g>
                )}
                <g
                  transform={`translate(${inp.x - p.x},${inp.y - p.y})`}
                  onPointerUp={(e) => onInputUp(e, n.id)}
                  className={readOnly ? '' : 'cursor-crosshair'}
                >
                  <circle r={10} fill="transparent" />
                  <circle r={5.5} className="fill-background stroke-muted-foreground" strokeWidth={2}>
                    <title>Drop to connect</title>
                  </circle>
                </g>
                {!readOnly &&
                  ports.map((port) => {
                    const o = portPosition('node', { x: 0, y: 0 }, port, ports);
                    return (
                      <g
                        key={port}
                        transform={`translate(${o.x},${o.y})`}
                        onPointerDown={(e) => onOutputDown(e, n.id, port)}
                        className="cursor-crosshair"
                      >
                        <circle r={10} fill="transparent" />
                        <circle r={5.5} className="fill-background stroke-primary" strokeWidth={2}>
                          <title>{`Drag from ${port} output`}</title>
                        </circle>
                        {ports.length > 1 && (
                          <text y={-10} textAnchor="middle" fontSize={10.5} fontWeight={700} className="fill-muted-foreground">
                            {port}
                          </text>
                        )}
                      </g>
                    );
                  })}
              </g>
            );
          })}
        </g>
      </svg>

      {/* controls */}
      <div className="absolute bottom-3 left-3 flex items-center gap-1 rounded-md border bg-card/95 p-1 shadow-sm">
        <button
          onClick={() => setView((v) => ({ ...v, k: Math.min(2, v.k * 1.2) }))}
          aria-label="Zoom in"
          className="rounded p-1.5 hover:bg-accent"
        >
          <Plus className="h-4 w-4" />
        </button>
        <button
          onClick={() => setView((v) => ({ ...v, k: Math.max(0.25, v.k / 1.2) }))}
          aria-label="Zoom out"
          className="rounded p-1.5 hover:bg-accent"
        >
          <Minus className="h-4 w-4" />
        </button>
        <button onClick={fitView} aria-label="Fit to view (F)" className="rounded p-1.5 hover:bg-accent">
          <Maximize className="h-4 w-4" />
        </button>
        <span className="px-1.5 text-xs tabular-nums text-muted-foreground" aria-live="polite">
          {Math.round(view.k * 100)}%
        </span>
      </div>

      {/* minimap */}
      <div className="absolute bottom-3 right-3 hidden sm:block">
        <WorkflowMinimap definition={definition} visible={visibleWorld} onNavigate={centerOn} />
      </div>

      {!readOnly && (
        <div className="absolute left-3 top-3 flex max-w-[calc(100%-24px)] items-center gap-2 rounded-md border bg-card/95 px-2.5 py-1.5 text-xs text-muted-foreground shadow-sm">
          <MousePointer2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="truncate">
            Drag to move · ports to connect · Shift+drag box-select · Ctrl+click multi · right-click menu · Del · Ctrl+C/V/D · F fit
            {selectedIds.length > 1 && <strong className="ml-1 text-foreground">{selectedIds.length} selected</strong>}
          </span>
        </div>
      )}

      {editor.pendingEdge && (
        <div className="absolute right-3 top-3 rounded-md border border-primary/40 bg-card/95 px-2.5 py-1.5 text-xs shadow-sm" role="status">
          Connecting from <span className="oa-code">{editor.pendingEdge.fromId}</span> — drop on an input port, Esc to cancel
        </div>
      )}

      {menu && (
        <CanvasContextMenu
          x={menu.x}
          y={menu.y}
          target={menu.target}
          hasClipboard={editor.hasClipboard}
          onAction={onMenuAction}
          onClose={() => setMenu(null)}
        />
      )}
    </div>
  );
}
