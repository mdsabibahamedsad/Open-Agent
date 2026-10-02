import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  buildZip,
  inspectPackage,
  packageProject,
  readZip,
} from "./packaging.js";

function makeProject(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "oa-pkg-"));
  fs.writeFileSync(
    path.join(dir, "openagent.yaml"),
    [
      `manifest_version: '1'`,
      `name: demo-ext`,
      `version: 0.1.0`,
      `type: tool`,
      `description: Demo extension for packaging tests.`,
      `license: MIT`,
      `runtime:`,
      `  entrypoint: src/index.ts`,
      `permissions:`,
      `  - fs:read`,
      `compatibility:`,
      `  openagent: '>=1.0.0 <2.0.0'`,
      ``,
    ].join("\n"),
  );
  fs.mkdirSync(path.join(dir, "src"), { recursive: true });
  fs.writeFileSync(path.join(dir, "src", "index.ts"), `export const x = 1;\n`);
  return dir;
}

describe("packaging", () => {
  it("is deterministic: build twice -> identical bytes", () => {
    const dir = makeProject();
    const a = packageProject(dir, { outPath: path.join(dir, "a.oaext") });
    const b = packageProject(dir, { outPath: path.join(dir, "b.oaext") });
    expect(fs.readFileSync(a.outPath).equals(fs.readFileSync(b.outPath))).toBe(
      true,
    );
    expect(a.sha256).toBe(b.sha256);
  });

  it("inspect ok and tamper detected", () => {
    const dir = makeProject();
    const built = packageProject(dir, {
      outPath: path.join(dir, "demo-ext-0.1.0.oaext"),
    });
    const info = inspectPackage(built.outPath);
    expect(info.checksumsOk).toBe(true);
    expect(info.entries).toContain("manifest.json");
    expect(info.entries).toContain("CHECKSUMS.sha256");

    // Tamper: flip a byte in the archive and expect verification to fail.
    const buf = fs.readFileSync(built.outPath);
    const tampered = Buffer.from(buf);
    tampered[tampered.length - 10] ^= 0xff;
    const tpath = path.join(dir, "tampered.oaext");
    fs.writeFileSync(tpath, tampered);
    expect(() => inspectPackage(tpath)).toThrow();
  });

  it("round-trips zip entries", () => {
    const zip = buildZip([
      { name: "b.txt", data: Buffer.from("hello") },
      { name: "a.txt", data: Buffer.from("world") },
    ]);
    const entries = readZip(zip);
    expect(entries.map((e) => e.name).sort()).toEqual(["a.txt", "b.txt"]);
  });
});
