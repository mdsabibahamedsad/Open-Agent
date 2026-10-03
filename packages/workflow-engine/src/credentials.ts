import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import type { CredentialResolver } from "./types.js";

function machineKey(): Buffer {
  // Stable-ish per-user key derived from env or OS user; credentials file is
  // obfuscated-at-rest + env override, documented as local-vault (not HSM).
  const seed =
    process.env.OPENAGENT_VAULT_KEY ??
    `${process.env.USERNAME ?? process.env.USER ?? "openagent"}@openagent-local-vault`;
  return crypto.createHash("sha256").update(seed).digest();
}

export function encryptValue(plain: string): string {
  const key = machineKey();
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const enc = Buffer.concat([cipher.update(plain, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `enc1.${iv.toString("base64")}.${tag.toString("base64")}.${enc.toString("base64")}`;
}

export function decryptValue(payload: string): string {
  if (!payload.startsWith("enc1.")) return payload; // plain legacy value
  const [, ivB64, tagB64, dataB64] = payload.split(".");
  const key = machineKey();
  const decipher = crypto.createDecipheriv(
    "aes-256-gcm",
    key,
    Buffer.from(ivB64, "base64"),
  );
  decipher.setAuthTag(Buffer.from(tagB64, "base64"));
  const dec = Buffer.concat([
    decipher.update(Buffer.from(dataB64, "base64")),
    decipher.final(),
  ]);
  return dec.toString("utf8");
}

export class FileCredentialResolver implements CredentialResolver {
  private store = new Map<string, string>();

  constructor(private projectDir?: string) {
    this.reload();
  }

  reload(): void {
    this.store.clear();
    if (!this.projectDir) return;
    const file = path.join(
      this.projectDir,
      ".openagent",
      "credentials",
      "vault.json",
    );
    try {
      if (!fs.existsSync(file)) return;
      const json = JSON.parse(fs.readFileSync(file, "utf8")) as Record<
        string,
        string
      >;
      for (const [k, v] of Object.entries(json)) {
        try {
          this.store.set(k, decryptValue(v));
        } catch {
          // keep raw on decrypt failure (key rotation case)
          this.store.set(k, v);
        }
      }
    } catch {
      // empty store on corrupt file; set() will repair on next write
    }
  }

  resolve(name: string): string | undefined {
    if (!name) return undefined;
    // Exact env match first (12-factor), then vault entry, then upper-snake env.
    if (process.env[name] !== undefined) return process.env[name];
    if (this.store.has(name)) return this.store.get(name);
    const upper = name.toUpperCase().replace(/[^A-Z0-9_]/g, "_");
    if (process.env[upper] !== undefined) return process.env[upper];
    return undefined;
  }

  set(name: string, value: string): void {
    if (!this.projectDir)
      throw new Error("no project dir for credential vault");
    const dir = path.join(this.projectDir, ".openagent", "credentials");
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, "vault.json");
    let json: Record<string, string> = {};
    try {
      if (fs.existsSync(file)) json = JSON.parse(fs.readFileSync(file, "utf8"));
    } catch {
      json = {};
    }
    json[name] = encryptValue(value);
    fs.writeFileSync(file, JSON.stringify(json, null, 2));
    this.reload();
  }

  list(): string[] {
    return [...this.store.keys()];
  }
}
