import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { findManifestPath, loadManifestFile } from "./validate.js";

// Deterministic .oaext packaging using only node built-ins.
// Fixed mtime 2019-01-01, sorted entries, deflate level 9, no extra fields.

export const FIXED_MTIME = new Date("2019-01-01T00:00:00Z");
const DOS_TIME = 0; // midnight
const DOS_DATE = ((2019 - 1980) << 9) | (1 << 5) | 1;

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

export function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]!) & 0xff]! ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

interface ZipEntry {
  name: string;
  data: Buffer;
  crc: number;
}

function dosDateTime(): { time: number; date: number } {
  return { time: DOS_TIME, date: DOS_DATE };
}

function localHeader(entry: ZipEntry, compressedSize: number): Buffer {
  const nameBuf = Buffer.from(entry.name, "utf8");
  const h = Buffer.alloc(30);
  h.writeUInt32LE(0x04034b50, 0); // signature
  h.writeUInt16LE(20, 4); // version needed
  h.writeUInt16LE(0x0800, 6); // UTF-8 flag
  h.writeUInt16LE(8, 8); // deflate
  const { time, date } = dosDateTime();
  h.writeUInt16LE(time, 10);
  h.writeUInt16LE(date, 12);
  h.writeUInt32LE(entry.crc, 14);
  h.writeUInt32LE(compressedSize, 18);
  h.writeUInt32LE(entry.data.length, 22);
  h.writeUInt16LE(nameBuf.length, 26);
  h.writeUInt16LE(0, 28); // extra len
  return Buffer.concat([h, nameBuf]);
}

function centralHeader(entry: ZipEntry, compressedSize: number, offset: number): Buffer {
  const nameBuf = Buffer.from(entry.name, "utf8");
  const h = Buffer.alloc(46);
  h.writeUInt32LE(0x02014b50, 0);
  h.writeUInt16LE(20, 4); // version made by
  h.writeUInt16LE(20, 6); // version needed
  h.writeUInt16LE(0x0800, 8);
  h.writeUInt16LE(8, 10);
  const { time, date } = dosDateTime();
  h.writeUInt16LE(time, 12);
  h.writeUInt16LE(date, 14);
  h.writeUInt32LE(entry.crc, 16);
  h.writeUInt32LE(compressedSize, 20);
  h.writeUInt32LE(entry.data.length, 24);
  h.writeUInt16LE(nameBuf.length, 28);
  h.writeUInt16LE(0, 30);
  h.writeUInt16LE(0, 32);
  h.writeUInt16LE(0, 34);
  h.writeUInt16LE(0, 36);
  h.writeUInt32LE(0o644 << 16, 38);
  h.writeUInt32LE(offset, 42);
  return Buffer.concat([h, nameBuf]);
}

/** Build a deterministic zip archive from sorted entries. */
export function buildZip(entries: Array<{ name: string; data: Buffer }>): Buffer {
  const sorted = [...entries].sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  for (const e of sorted) {
    if (e.name.startsWith("/") || e.name.includes("\\") || e.name.split("/").includes("..")) {
      throw new Error(`Unsafe zip entry name: ${e.name}`);
    }
  }
  const zipped: Array<{ entry: ZipEntry; compressed: Buffer }> = sorted.map((e) => {
    const data = Buffer.from(e.data);
    const compressed = zlib.deflateRawSync(data, { level: 9, memLevel: 9 });
    return { entry: { name: e.name, data, crc: crc32(data) }, compressed };
  });
  const chunks: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const z of zipped) {
    const lh = localHeader(z.entry, z.compressed.length);
    chunks.push(lh, z.compressed);
    centrals.push(centralHeader(z.entry, z.compressed.length, offset));
    offset += lh.length + z.compressed.length;
  }
  const centralStart = offset;
  let centralSize = 0;
  for (const c of centrals) {
    chunks.push(c);
    centralSize += c.length;
  }
  const count = centrals.length;
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(count, 8);
  end.writeUInt16LE(count, 10);
  end.writeUInt32LE(centralSize, 12);
  end.writeUInt32LE(centralStart, 16);
  end.writeUInt16LE(0, 20);
  chunks.push(end);
  return Buffer.concat(chunks);
}

/** Minimal zip reader: parse central directory, extract entries with zip-slip guard. */
export function readZip(buf: Buffer): Array<{ name: string; data: Buffer }> {
  const endSig = 0x06054b50;
  let endOffset = -1;
  for (let i = buf.length - 22; i >= 0; i--) {
    if (buf.readUInt32LE(i) === endSig) {
      endOffset = i;
      break;
    }
  }
  if (endOffset < 0) throw new Error("Invalid archive: end-of-central-directory not found.");
  const count = buf.readUInt16LE(endOffset + 10);
  const centralSize = buf.readUInt32LE(endOffset + 12);
  const centralOffset = buf.readUInt32LE(endOffset + 16);
  if (centralOffset + centralSize > buf.length) throw new Error("Invalid archive: central directory out of bounds.");
  interface Central { name: string; localOffset: number; compSize: number; size: number; method: number; crc: number }
  const centrals: Central[] = [];
  let p = centralOffset;
  for (let i = 0; i < count; i++) {
    if (buf.readUInt32LE(p) !== 0x02014b50) throw new Error("Invalid archive: bad central header.");
    const method = buf.readUInt16LE(p + 10);
    const crc = buf.readUInt32LE(p + 16);
    const compSize = buf.readUInt32LE(p + 20);
    const size = buf.readUInt32LE(p + 24);
    const nameLen = buf.readUInt16LE(p + 28);
    const extraLen = buf.readUInt16LE(p + 30);
    const commentLen = buf.readUInt16LE(p + 32);
    const localOffset = buf.readUInt32LE(p + 42);
    const name = buf.subarray(p + 46, p + 46 + nameLen).toString("utf8");
    centrals.push({ name, localOffset, compSize, size, method, crc });
    p += 46 + nameLen + extraLen + commentLen;
  }
  const out: Array<{ name: string; data: Buffer }> = [];
  for (const c of centrals) {
    assertSafeName(c.name);
    if (buf.readUInt32LE(c.localOffset) !== 0x04034b50) throw new Error(`Invalid archive: bad local header for ${c.name}.`);
    const nameLen = buf.readUInt16LE(c.localOffset + 26);
    const extraLen = buf.readUInt16LE(c.localOffset + 28);
    const dataStart = c.localOffset + 30 + nameLen + extraLen;
    const comp = buf.subarray(dataStart, dataStart + c.compSize);
    let raw: Buffer;
    if (c.method === 0) raw = Buffer.from(comp);
    else if (c.method === 8) raw = zlib.inflateRawSync(comp);
    else throw new Error(`Unsupported compression method ${c.method} for ${c.name}.`);
    if (raw.length !== c.size) throw new Error(`Size mismatch for ${c.name}. Archive may be tampered.`);
    if (crc32(raw) !== c.crc) throw new Error(`Checksum mismatch for ${c.name}. Archive may be tampered.`);
    out.push({ name: c.name, data: raw });
  }
  return out;
}

function assertSafeName(name: string): void {
  if (name.startsWith("/") || name.includes("\\") || name.split("/").includes("..") || name.includes("\0")) {
    throw new Error(`Unsafe entry name in archive: ${name}`);
  }
}

const EXCLUDE_DIRS = new Set(["node_modules", ".git", "dist", ".venv", "__pycache__", ".turbo", "coverage"]);

export function collectProjectFiles(projectDir: string): Array<{ name: string; data: Buffer }> {
  const out: Array<{ name: string; data: Buffer }> = [];
  const walk = (dir: string, rel: string) => {
    const entries = fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name));
    for (const e of entries) {
      if (e.name === "openagent.yaml" || e.name === "openagent.yml" || e.name === "openagent.json") continue;
      if (e.name.endsWith(".oaext")) continue;
      const full = path.join(dir, e.name);
      const r = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) {
        if (EXCLUDE_DIRS.has(e.name)) continue;
        walk(full, r);
      } else if (e.isFile()) {
        out.push({ name: `files/${r}`, data: fs.readFileSync(full) });
      }
    }
  };
  walk(projectDir, "");
  return out;
}

export function sha256Hex(data: Buffer | string): string {
  return crypto.createHash("sha256").update(data).digest("hex");
}

export interface PackageOptions {
  outPath?: string;
  buildTime?: string;
}

export interface PackageResult {
  outPath: string;
  bytes: number;
  sha256: string;
  entryCount: number;
}

export function packageProject(projectDir: string, opts: PackageOptions = {}): PackageResult {
  const abs = path.resolve(projectDir);
  const manifestPath = findManifestPath(abs);
  if (!manifestPath) throw new Error(`No openagent manifest found in ${abs}. Run \`openagent init\` first.`);
  const { manifest } = loadManifestFile(manifestPath);
  const m = manifest as Record<string, unknown>;
  const name = String(m.name ?? "extension");
  const version = String(m.version ?? "0.1.0");
  const buildTime = opts.buildTime ?? "2019-01-01T00:00:00.000Z";
  const manifestJson = Buffer.from(JSON.stringify(m, null, 2) + "\n", "utf8");
  const projectFiles = collectProjectFiles(abs);
  const sbom = Buffer.from(
    JSON.stringify({ bomFormat: "CycloneDX", specVersion: "1.5", version: 1, metadata: { component: { name, version }, timestamp: buildTime }, components: [] }, null, 2) + "\n",
    "utf8",
  );
  const provenance = Buffer.from(
    JSON.stringify({ builder: "openagent-cli/1.0.0", buildTime, source: { manifest: path.basename(manifestPath) }, reproducible: true }, null, 2) + "\n",
    "utf8",
  );
  const signatures = Buffer.from(JSON.stringify({ signatures: [] }, null, 2) + "\n", "utf8");
  const parts: Array<{ name: string; data: Buffer }> = [
    { name: "manifest.json", data: manifestJson },
    ...projectFiles,
    { name: "SBOM.json", data: sbom },
    { name: "provenance.json", data: provenance },
    { name: "signatures.json", data: signatures },
  ];
  const checksums = [...parts]
    .sort((a, b) => (a.name < b.name ? -1 : 1))
    .map((e) => `${sha256Hex(e.data)}  ${e.name}`)
    .join("\n") + "\n";
  parts.push({ name: "CHECKSUMS.sha256", data: Buffer.from(checksums, "utf8") });
  const zip = buildZip(parts);
  const outPath = opts.outPath ?? path.join(abs, `${name}-${version}.oaext`);
  fs.writeFileSync(outPath, zip);
  return { outPath, bytes: zip.length, sha256: sha256Hex(zip), entryCount: parts.length };
}

export interface InspectResult {
  path: string;
  entries: string[];
  manifest: Record<string, unknown>;
  checksumsOk: boolean;
  files: number;
}

export function inspectPackage(archivePath: string): InspectResult {
  const buf = fs.readFileSync(archivePath);
  const entries = readZip(buf);
  for (const e of entries) assertSafeName(e.name);
  const names = entries.map((e) => e.name);
  const manifestEntry = entries.find((e) => e.name === "manifest.json");
  if (!manifestEntry) throw new Error("Invalid .oaext: manifest.json missing.");
  const checksumEntry = entries.find((e) => e.name === "CHECKSUMS.sha256");
  if (!checksumEntry) throw new Error("Invalid .oaext: CHECKSUMS.sha256 missing.");
  const manifest = JSON.parse(manifestEntry.data.toString("utf8")) as Record<string, unknown>;
  const lines = checksumEntry.data.toString("utf8").split("\n").filter((l) => l.trim() !== "");
  const expected = new Map<string, string>();
  for (const line of lines) {
    const mm = line.match(/^([0-9a-f]{64})\s+(.+)$/);
    if (!mm) throw new Error(`Invalid CHECKSUMS.sha256 line: ${line}`);
    expected.set(mm[2]!.trim(), mm[1]!.toLowerCase());
  }
  let checksumsOk = true;
  for (const e of entries) {
    if (e.name === "CHECKSUMS.sha256") continue;
    const want = expected.get(e.name);
    if (!want || sha256Hex(e.data).toLowerCase() !== want) {
      checksumsOk = false;
      break;
    }
  }
  if (!checksumsOk) throw new Error("Checksum verification FAILED: archive tampered or corrupt.");
  const files = entries.filter((e) => e.name.startsWith("files/")).length;
  return { path: archivePath, entries: names.sort(), manifest, checksumsOk: true, files };
}
