import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

export interface DownloadProgress {
  downloadedBytes: number;
  totalBytes: number | null;
  percent: number | null;
}

export interface DownloadOptions {
  url: string;
  dest: string;
  expectedSha256?: string;
  timeoutMs?: number;
  onProgress?: (p: DownloadProgress) => void;
  signal?: AbortSignal;
}

interface ResumeState {
  url: string;
  downloadedBytes: number;
}

function stateFile(dest: string): string {
  return `${dest}.oa-download.json`;
}

function sha256File(file: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const h = crypto.createHash("sha256");
    const s = fs.createReadStream(file);
    s.on("data", (c) => h.update(c));
    s.on("end", () => resolve(h.digest("hex")));
    s.on("error", reject);
  });
}

/**
 * Resumable HTTPS download. Never restarts from zero after a failure:
 * partial data lives in `<dest>.part` plus a sidecar state file, and
 * subsequent calls resume with `Range` requests when the server allows it.
 */
export async function downloadFile(
  opts: DownloadOptions,
): Promise<{ path: string; bytes: number; resumed: boolean }> {
  const { url, dest, timeoutMs = 120000 } = opts;
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const part = `${dest}.part`;
  let start = 0;
  let resumed = false;

  try {
    if (fs.existsSync(part) && fs.existsSync(stateFile(dest))) {
      const st = JSON.parse(
        fs.readFileSync(stateFile(dest), "utf8"),
      ) as ResumeState;
      const size = fs.statSync(part).size;
      if (st.url === url && st.downloadedBytes === size && size > 0) {
        start = size;
        resumed = true;
      }
    }
  } catch {
    start = 0;
    resumed = false;
  }

  const headers: Record<string, string> = {
    "user-agent": "openagent-installer/1.0",
  };
  if (start > 0) headers.Range = `bytes=${start}-`;

  const ctrl = new AbortController();
  const timer = setTimeout(
    () => ctrl.abort(new Error(`download timed out: ${url}`)),
    timeoutMs,
  );
  if (opts.signal) {
    opts.signal.addEventListener(
      "abort",
      () => ctrl.abort(opts.signal?.reason),
      { once: true },
    );
  }

  let res: Response;
  try {
    res = await fetch(url, { headers, signal: ctrl.signal });
  } catch (e) {
    clearTimeout(timer);
    throw e;
  }
  if (res.status !== 200 && res.status !== 206) {
    clearTimeout(timer);
    throw new Error(`download HTTP ${res.status} for ${url}`);
  }
  if (start > 0 && res.status === 200) {
    // Server ignored Range — restart cleanly (only case that restarts).
    start = 0;
    resumed = false;
    try {
      fs.rmSync(part);
    } catch {
      // ignore
    }
  }

  const totalHeader = res.headers.get("content-length");
  const total = totalHeader ? start + Number(totalHeader) : null;

  const fh = fs.openSync(part, start > 0 ? "r+" : "w");
  try {
    fs.ftruncateSync(fh, start);
    fs.writeSync(fh, Buffer.alloc(0), 0, 0, start);
  } catch {
    // positions will be explicit below
  }
  let written = start;
  const persist = () => {
    try {
      fs.writeFileSync(
        stateFile(dest),
        JSON.stringify({ url, downloadedBytes: written }),
      );
    } catch {
      // best effort
    }
  };
  persist();

  try {
    const reader = res.body?.getReader();
    if (!reader) throw new Error("empty response body");
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        fs.writeSync(fh, Buffer.from(value), 0, value.length, written);
        written += value.length;
        if (written % (256 * 1024) < value.length) persist();
        opts.onProgress?.({
          downloadedBytes: written,
          totalBytes: total,
          percent: total ? Math.min(100, (written / total) * 100) : null,
        });
      }
    }
  } finally {
    clearTimeout(timer);
    try {
      fs.closeSync(fh);
    } catch {
      // ignore
    }
    await res.body?.cancel().catch(() => undefined);
  }

  if (opts.expectedSha256) {
    const actual = await sha256File(part);
    if (actual.toLowerCase() !== opts.expectedSha256.toLowerCase()) {
      throw new Error(
        `checksum mismatch for ${path.basename(dest)} (corrupted download detected; delete the .part file to retry)`,
      );
    }
  }

  fs.renameSync(part, dest);
  try {
    fs.rmSync(stateFile(dest));
  } catch {
    // ignore
  }
  opts.onProgress?.({
    downloadedBytes: written,
    totalBytes: written,
    percent: 100,
  });
  return { path: dest, bytes: written, resumed };
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1073741824) return `${(n / 1048576).toFixed(1)} MB`;
  return `${(n / 1073741824).toFixed(2)} GB`;
}
