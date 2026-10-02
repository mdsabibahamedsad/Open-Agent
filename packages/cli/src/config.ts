import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export interface ProfileConfig {
  apiUrl: string;
  apiKey?: string;
  orgId?: string;
}

export interface FileConfig {
  activeProfile: string;
  profiles: Record<string, ProfileConfig>;
}

export const DEFAULT_API_URL = "http://localhost:8000";
export const DEFAULT_PROFILE = "default";

export function configDir(): string {
  const custom = process.env.OPENAGENT_CONFIG_DIR;
  if (custom && custom.trim() !== "") return custom;
  return path.join(os.homedir(), ".config", "openagent");
}

export function configFilePath(): string {
  return path.join(configDir(), "config.json");
}

export function registryDir(): string {
  return path.join(configDir(), "registry");
}

function readFileConfig(): FileConfig {
  const file = configFilePath();
  try {
    const raw = fs.readFileSync(file, "utf8");
    const parsed = JSON.parse(raw) as Partial<FileConfig>;
    return {
      activeProfile: typeof parsed.activeProfile === "string" ? parsed.activeProfile : DEFAULT_PROFILE,
      profiles:
        parsed.profiles && typeof parsed.profiles === "object" ? (parsed.profiles as Record<string, ProfileConfig>) : {},
    };
  } catch {
    return { activeProfile: DEFAULT_PROFILE, profiles: {} };
  }
}

function writeFileConfig(cfg: FileConfig): void {
  fs.mkdirSync(configDir(), { recursive: true, mode: 0o700 });
  const tmp = `${configFilePath()}.tmp-${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(cfg, null, 2) + "\n", { mode: 0o600 });
  fs.renameSync(tmp, configFilePath());
  try {
    fs.chmodSync(configFilePath(), 0o600);
  } catch {
    // best-effort on Windows
  }
}

export interface ResolvedProfile extends ProfileConfig {
  name: string;
  fromEnv: { apiUrl: boolean; apiKey: boolean; orgId: boolean };
}

function envVal(name: string): string | undefined {
  const v = process.env[name];
  if (v === undefined) return undefined;
  const t = v.trim();
  return t === "" ? undefined : t;
}

/** Resolve effective profile: env vars take precedence over stored file. */
export function getProfile(nameOverride?: string, orgOverride?: string): ResolvedProfile {
  const fileCfg = readFileConfig();
  const requested =
    nameOverride?.trim() ||
    envVal("OPENAGENT_PROFILE") ||
    fileCfg.activeProfile ||
    DEFAULT_PROFILE;
  const stored: ProfileConfig = fileCfg.profiles[requested] ?? {};
  const envApiUrl = envVal("OPENAGENT_API_URL");
  const envApiKey = envVal("OPENAGENT_API_KEY");
  const envOrg = envVal("OPENAGENT_ORG_ID");

  const apiUrl = (envApiUrl ?? stored.apiUrl ?? DEFAULT_API_URL).replace(/\/+$/, "");
  const apiKey = envApiKey ?? stored.apiKey;
  const orgId = orgOverride?.trim() || envOrg || stored.orgId;

  return {
    name: requested,
    apiUrl,
    apiKey,
    orgId,
    fromEnv: {
      apiUrl: envApiUrl !== undefined,
      apiKey: envApiKey !== undefined,
      orgId: envOrg !== undefined || orgOverride !== undefined,
    },
  };
}

export function saveProfile(
  name: string,
  patch: Partial<ProfileConfig> & { makeActive?: boolean },
): void {
  const cfg = readFileConfig();
  const key = name.trim() || DEFAULT_PROFILE;
  const prev = cfg.profiles[key] ?? {};
  const next: ProfileConfig = {
    apiUrl: (patch.apiUrl ?? prev.apiUrl ?? DEFAULT_API_URL).replace(/\/+$/, ""),
    apiKey: patch.apiKey !== undefined ? patch.apiKey : prev.apiKey,
    orgId: patch.orgId !== undefined ? patch.orgId : prev.orgId,
  };
  if (next.apiKey === undefined) delete next.apiKey;
  if (next.orgId === undefined) delete next.orgId;
  cfg.profiles[key] = next;
  if (patch.makeActive !== false) cfg.activeProfile = key;
  writeFileConfig(cfg);
}

export function removeProfileSecrets(name: string): boolean {
  const cfg = readFileConfig();
  const key = name.trim() || DEFAULT_PROFILE;
  const existing = cfg.profiles[key];
  if (!existing) return false;
  delete existing.apiKey;
  cfg.profiles[key] = existing;
  writeFileConfig(cfg);
  return true;
}

export function listProfiles(): { active: string; names: string[]; raw: FileConfig } {
  const cfg = readFileConfig();
  return { active: cfg.activeProfile, names: Object.keys(cfg.profiles).sort(), raw: cfg };
}

export function maskApiKey(key?: string): string {
  if (!key) return "(none)";
  const t = key.trim();
  if (t.length <= 4) return "****";
  return `${"*".repeat(Math.min(8, t.length - 4))}${t.slice(-4)}`;
}

/** Redact secret-looking values from arbitrary JSON for safe display. */
export function redactSecrets(value: unknown): unknown {
  if (value === null || value === undefined) return value;
  if (typeof value === "string") {
    if (/^(sk-|ghp_|gho_|AKIA|Bearer\s)/.test(value) || value.length >= 20) {
      // Only mask long opaque strings; keep short readable values intact.
      if (value.length >= 24 || /sk-|ghp_|AKIA|PRIVATE KEY/i.test(value)) return maskApiKey(value);
    }
    return value;
  }
  if (Array.isArray(value)) return value.map(redactSecrets);
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (/api[_-]?key|token|secret|password|private[_-]?key|credential/i.test(k)) {
        out[k] = typeof v === "string" ? maskApiKey(v) : "(redacted)";
      } else {
        out[k] = redactSecrets(v);
      }
    }
    return out;
  }
  return value;
}
