import { createHash } from "node:crypto";

/** Credential boundary: models only ever see references, never secrets. */
export interface CredentialRef {
  reference: string;
  domain?: string;
}

const SENSITIVE_KEYS = [
  "password",
  "passwd",
  "secret",
  "api_key",
  "apikey",
  "token",
  "cookie",
  "auth",
  "authorization",
  "private_key",
  "client_secret",
];

export function redactSecrets<T>(value: T): T {
  if (typeof value === "string") {
    return value
      .replace(
        /(sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16})/g,
        "[REDACTED]",
      )
      .replace(
        /(password|secret|api[_-]?key|token)\s*[:=]\s*\S+/gi,
        "$1=[REDACTED]",
      ) as unknown as T;
  }
  if (Array.isArray(value)) return value.map(redactSecrets) as unknown as T;
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = SENSITIVE_KEYS.includes(k.toLowerCase())
        ? "[REDACTED]"
        : redactSecrets(v);
    }
    return out as unknown as T;
  }
  return value;
}

const INJECTION_PATTERNS = [
  /ignore\s+(all\s+)?(previous|prior|above)\s+instructions/i,
  /reveal\s+(your\s+)?(system\s+prompt|instructions|secret)/i,
  /send\s+(secrets?|cookies?|passwords?|tokens?|credentials?)\s+to\b/i,
  /transfer\s+(money|funds)\b/i,
  /delete\s+(all\s+)?(data|database|files)\b/i,
  /disable\s+(security|safety|guardrails?)\b/i,
  /you\s+are\s+now\s+(in\s+)?(developer|admin|root|god)\s+mode/i,
];

export function detectPromptInjection(webText: string): string[] {
  const hits: string[] = [];
  for (const pat of INJECTION_PATTERNS) {
    const m = webText.match(pat);
    if (m) hits.push(m[0].slice(0, 120));
  }
  return hits;
}

export function labelUntrusted(content: string, limit = 8000): string {
  const body =
    content.length > limit
      ? content.slice(0, limit) + "... [truncated]"
      : content;
  return `[UNTRUSTED_WEB_CONTENT]\n${body}\n[/UNTRUSTED_WEB_CONTENT]`;
}

const CHALLENGE_SIGNALS: Record<string, string[]> = {
  CAPTCHA: ["captcha", "recaptcha", "hcaptcha", "prove you are human"],
  MFA_REQUIRED: ["two-factor", "2fa", "verification code", "authenticator"],
  LOGIN_REQUIRED: [
    "sign in to continue",
    "log in to continue",
    "session expired",
  ],
  SECURITY_CHECK: ["security check", "unusual traffic", "access denied"],
  BOT_CHALLENGE: ["are you a robot", "cloudflare", "press & hold"],
};

export function detectChallenge(pageText: string, title = ""): string | null {
  const blob = `${title}\n${pageText}`.toLowerCase();
  for (const [kind, signals] of Object.entries(CHALLENGE_SIGNALS)) {
    if (signals.some((s) => blob.includes(s))) return kind;
  }
  return null;
}

export function sha256(s: string): string {
  return createHash("sha256").update(s, "utf8").digest("hex");
}

export interface StateFingerprintInput {
  url: string;
  title: string;
  text: string;
  elements: Array<{ role?: string; name?: string } | string>;
}

export function fingerprintState(input: StateFingerprintInput) {
  const elSig = input.elements
    .map((e) => (typeof e === "string" ? e : `${e.role ?? ""}:${e.name ?? ""}`))
    .sort()
    .join("|");
  return {
    url: input.url,
    title: input.title,
    textHash: sha256(input.text ?? ""),
    domHash: sha256(
      `${input.url}|${input.title}|${(input.text ?? "").slice(0, 2000)}`,
    ),
    interactiveElementsHash: sha256(elSig),
    timestamp: new Date(),
  };
}

export function sanitizeFilename(name: string): string {
  return name.replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 200) || "download";
}
