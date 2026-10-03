import fs from "node:fs";
import path from "node:path";
import { embedText } from "./providers.js";
import type { MemoryManager, MemoryRecord } from "./types.js";

function cosine(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  let dot = 0;
  for (let i = 0; i < n; i++) dot += (a[i] ?? 0) * (b[i] ?? 0);
  return dot;
}

/** File-backed memory: short-term KV + append-only episodic log + hashed semantic index. */
export class FileMemoryManager implements MemoryManager {
  private kv = new Map<string, unknown>();
  private file: string;

  constructor(projectDir: string | undefined, executionId?: string) {
    const base = projectDir
      ? path.join(projectDir, ".openagent", "memory")
      : path.join(process.cwd(), ".openagent", "memory");
    fs.mkdirSync(base, { recursive: true });
    this.file = path.join(base, "memory.json");
    this.load();
    void executionId;
  }

  private load(): void {
    try {
      if (!fs.existsSync(this.file)) return;
      const json = JSON.parse(fs.readFileSync(this.file, "utf8")) as Record<
        string,
        unknown
      >;
      for (const [k, v] of Object.entries(json)) this.kv.set(k, v);
    } catch {
      // start empty on corrupt file
    }
  }

  private persist(): void {
    try {
      fs.writeFileSync(
        this.file,
        JSON.stringify(Object.fromEntries(this.kv), null, 2),
      );
    } catch {
      // best-effort persistence
    }
  }

  async get(key: string): Promise<unknown> {
    return this.kv.get(key);
  }

  async set(key: string, value: unknown): Promise<void> {
    this.kv.set(key, value);
    this.persist();
  }

  async append(key: string, value: unknown): Promise<void> {
    const cur = this.kv.get(key);
    const arr = Array.isArray(cur) ? cur : cur === undefined ? [] : [cur];
    arr.push({ ts: new Date().toISOString(), value });
    this.kv.set(key, arr);
    this.persist();
  }

  async search(query: string, limit = 5): Promise<MemoryRecord[]> {
    const q = await embedText(query);
    const scored: Array<{ rec: MemoryRecord; score: number }> = [];
    for (const [key, value] of this.kv) {
      const text = `${key} ${JSON.stringify(value)}`;
      const emb = await embedText(text);
      scored.push({
        rec: {
          key,
          value,
          embedding: emb,
          createdAt: new Date().toISOString(),
        },
        score: cosine(q, emb),
      });
    }
    return scored
      .sort((a, b) => b.score - a.score)
      .slice(0, limit)
      .map((s) => s.rec);
  }
}

export class InMemoryMemoryManager implements MemoryManager {
  private kv = new Map<string, unknown>();
  async get(key: string): Promise<unknown> {
    return this.kv.get(key);
  }
  async set(key: string, value: unknown): Promise<void> {
    this.kv.set(key, value);
  }
  async append(key: string, value: unknown): Promise<void> {
    const cur = this.kv.get(key);
    const arr = Array.isArray(cur) ? cur : cur === undefined ? [] : [cur];
    arr.push({ ts: new Date().toISOString(), value });
    this.kv.set(key, arr);
  }
  async search(query: string, limit = 5): Promise<MemoryRecord[]> {
    const q = await embedText(query);
    const out: MemoryRecord[] = [];
    for (const [key, value] of this.kv) {
      const emb = await embedText(`${key} ${JSON.stringify(value)}`);
      void cosine(q, emb);
      out.push({
        key,
        value,
        embedding: emb,
        createdAt: new Date().toISOString(),
      });
    }
    return out.slice(0, limit);
  }
}
