import type { BrowserObservationStrategy } from '../core/types';

const BUDGETS: Record<string, number> = {
  minimal: 1500,
  standard: 6000,
  detailed: 15000,
  visual: 6000,
  custom: 6000,
};

export function compressObservationText(
  url: string,
  title: string,
  elements: Array<{ role?: string; name?: string; selector?: string; visible?: boolean }>,
  text = '',
  strategy: BrowserObservationStrategy = 'standard',
): string {
  const budget = BUDGETS[strategy] ?? 6000;
  const lines: string[] = [`Current URL: ${url}`, `Page title: ${title}`, '', 'Visible interactive elements:'];
  const seen = new Set<string>();
  const cap = strategy === 'minimal' ? 20 : strategy === 'standard' ? 60 : 120;
  for (const el of elements) {
    if (el.visible === false) continue;
    const sig = `${el.role}:${el.name}:${el.selector}`;
    if (seen.has(sig)) continue;
    seen.add(sig);
    lines.push(`- ${el.role ?? 'element'}: ${String(el.name ?? el.selector ?? el.role).slice(0, 80)}`);
    if (lines.length > cap + 4) break;
  }
  if (strategy !== 'minimal' && text) {
    lines.push('', 'Relevant text:', dedupLines(text).slice(0, Math.max(500, budget >> 1)));
  }
  const out = lines.join('\n');
  return out.length > budget ? out.slice(0, budget) + '... [truncated]' : out;
}

function dedupLines(text: string): string {
  const seen = new Set<string>();
  const kept: string[] = [];
  for (const line of text.split('\n')) {
    const s = line.replace(/\s+/g, ' ').trim();
    if (!s || seen.has(s)) continue;
    seen.add(s);
    kept.push(s);
  }
  return kept.join('\n');
}
