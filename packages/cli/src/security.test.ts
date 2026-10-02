import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { scanDirectory } from "./security.js";

function makeTmp(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), "oa-sec-"));
}

describe("security scan", () => {
  it("detects AWS key and blocks publish", () => {
    const dir = makeTmp();
    fs.writeFileSync(
      path.join(dir, "app.ts"),
      `const k = "AKIAIOSFODNN7EXAMPLE";\n`,
    );
    const res = scanDirectory(dir);
    expect(res.findings.some((f) => f.rule === "aws-access-key")).toBe(true);
    expect(res.blocksPublish).toBe(true);
  });

  it("detects private key and blocks publish", () => {
    const dir = makeTmp();
    fs.writeFileSync(
      path.join(dir, "key.pem"),
      `-----BEGIN RSA PRIVATE KEY-----\nabc\n`,
    );
    const res = scanDirectory(dir);
    expect(res.findings.some((f) => f.rule === "private-key")).toBe(true);
    expect(res.blocksPublish).toBe(true);
  });

  it("detects postgres DSN with password", () => {
    const dir = makeTmp();
    fs.writeFileSync(
      path.join(dir, "cfg.ts"),
      `const dsn = "postgres://alice:s3cret@db:5432/app";\n`,
    );
    const res = scanDirectory(dir);
    expect(
      res.findings.some((f) => f.rule === "postgres-dsn-with-password"),
    ).toBe(true);
  });

  it("passes clean code", () => {
    const dir = makeTmp();
    fs.writeFileSync(
      path.join(dir, "clean.ts"),
      `export const x = 1;\n// reads secret from SECRET_REF at runtime\n`,
    );
    const res = scanDirectory(dir);
    expect(res.findings).toEqual([]);
    expect(res.blocksPublish).toBe(false);
  });
});
