import fs from "node:fs";
import path from "node:path";

export interface SecretFinding {
  file: string;
  line: number;
  rule: string;
  severity: "critical" | "high" | "medium";
  snippet: string;
}

export interface ScanResult {
  findings: SecretFinding[];
  blocksPublish: boolean;
}

interface Pattern {
  rule: string;
  severity: SecretFinding["severity"];
  regex: RegExp;
  blocksPublish: boolean;
  redact?: boolean;
}

const SECRET_PATTERNS: Pattern[] = [
  {
    rule: "aws-access-key",
    severity: "critical",
    regex: /AKIA[0-9A-Z]{16}/,
    blocksPublish: true,
  },
  {
    rule: "private-key",
    severity: "critical",
    regex: /BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY/,
    blocksPublish: true,
  },
  {
    rule: "openai-key",
    severity: "critical",
    regex: /sk-[A-Za-z0-9]{20,}/,
    blocksPublish: true,
  },
  {
    rule: "github-token",
    severity: "critical",
    regex: /ghp_[A-Za-z0-9]{20,}/,
    blocksPublish: true,
  },
  {
    rule: "github-oauth",
    severity: "critical",
    regex: /gho_[A-Za-z0-9]{20,}/,
    blocksPublish: true,
  },
  {
    rule: "api-key-assignment",
    severity: "high",
    regex: /\bapi[_-]?key\s*[:=]\s*['"][^'"]{8,}['"]/i,
    blocksPublish: true,
  },
  {
    rule: "client-secret-assignment",
    severity: "high",
    regex: /\bclient[_-]?secret\s*[:=]\s*['"][^'"]{4,}['"]/i,
    blocksPublish: true,
  },
  {
    rule: "password-assignment",
    severity: "high",
    regex: /\bpassword\s*[:=]\s*['"][^'"]{4,}['"]/i,
    blocksPublish: true,
  },
  {
    rule: "bearer-token",
    severity: "high",
    regex: /Bearer\s+[A-Za-z0-9\-._~+/]{16,}={0,2}/,
    blocksPublish: true,
  },
  {
    rule: "postgres-dsn-with-password",
    severity: "high",
    regex: /postgres(?:ql)?:\/\/[^/\s:]+:[^/\s@]+@[^\s'"]+/,
    blocksPublish: true,
  },
  {
    rule: "generic-secret-assignment",
    severity: "medium",
    regex: /\bsecret\s*[:=]\s*['"][^'"]{4,}['"]/i,
    blocksPublish: false,
  },
];

const DANGEROUS_PATTERNS: Pattern[] = [
  {
    rule: "js-eval",
    severity: "high",
    regex: /\beval\s*\(/,
    blocksPublish: true,
  },
  {
    rule: "js-child-process",
    severity: "high",
    regex:
      /require\s*\(\s*['"]child_process['"]\s*\)|from\s+['"]child_process['"]/,
    blocksPublish: true,
  },
  {
    rule: "py-os-system",
    severity: "high",
    regex: /\bos\.system\s*\(/,
    blocksPublish: true,
  },
  {
    rule: "py-subprocess-shell",
    severity: "high",
    regex: /subprocess\.\w+\(.*shell\s*=\s*True/,
    blocksPublish: true,
  },
  {
    rule: "docker-sock",
    severity: "critical",
    regex: /docker\.sock/,
    blocksPublish: true,
  },
  {
    rule: "pickle-loads",
    severity: "high",
    regex: /pickle\.loads?\s*\(/,
    blocksPublish: true,
  },
  {
    rule: "preinstall-hook",
    severity: "high",
    regex: /"(preinstall|postinstall)"\s*:/,
    blocksPublish: true,
  },
];

const SKIP_DIRS = new Set([
  "node_modules",
  ".git",
  "dist",
  "build",
  ".next",
  "out",
  ".venv",
  "venv",
  "__pycache__",
  ".pytest_cache",
  ".mypy_cache",
  ".ruff_cache",
  ".turbo",
  "coverage",
  "htmlcov",
]);
const SKIP_EXTS = new Set([
  ".oaext",
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".pdf",
  ".zip",
  ".tar",
  ".gz",
]);
const MAX_FILE_BYTES = 1024 * 1024;

function redactSnippet(s: string): string {
  let out = s.trim();
  if (out.length > 160) out = out.slice(0, 160) + "…";
  // Mask long token-like substrings.
  out = out.replace(/sk-[A-Za-z0-9]{8,}/g, "sk-****");
  out = out.replace(/AKIA[0-9A-Z]{8,}/g, "AKIA****");
  out = out.replace(/ghp_[A-Za-z0-9]{8,}/g, "ghp_****");
  out = out.replace(/(password\s*[:=]\s*['"])[^'"]{2,}(['"])/i, "$1****$2");
  return out;
}

function listFiles(root: string): string[] {
  const out: string[] = [];
  const stack = [root];
  while (stack.length > 0) {
    const dir = stack.pop() as string;
    let entries: string[];
    try {
      entries = fs.readdirSync(dir);
    } catch {
      continue;
    }
    for (const e of entries.sort()) {
      if (e === ".git" || e === "node_modules") continue;
      const full = path.join(dir, e);
      let st: fs.Stats;
      try {
        st = fs.statSync(full);
      } catch {
        continue;
      }
      if (st.isDirectory()) {
        if (SKIP_DIRS.has(e)) continue;
        stack.push(full);
      } else if (st.isFile()) {
        if (st.size > MAX_FILE_BYTES) continue;
        if (SKIP_EXTS.has(path.extname(e).toLowerCase())) continue;
        const base = path.basename(full);
        if (base === "package-lock.json" || base === "pnpm-lock.yaml") continue;
        out.push(full);
      }
    }
  }
  return out.sort();
}

export function isProbablyBinary(buf: Buffer): boolean {
  const n = Math.min(buf.length, 4096);
  for (let i = 0; i < n; i++) {
    if (buf[i] === 0) return true;
  }
  return false;
}

export function scanDirectory(
  root: string,
  opts?: { extraPatterns?: RegExp[] },
): ScanResult {
  const findings: SecretFinding[] = [];
  const files = listFiles(root);
  const allPatterns = [...SECRET_PATTERNS, ...DANGEROUS_PATTERNS];
  for (const file of files) {
    let buf: Buffer;
    try {
      buf = fs.readFileSync(file);
    } catch {
      continue;
    }
    if (isProbablyBinary(buf)) continue;
    const text = buf.toString("utf8");
    const lines = text.split("\n");
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i] as string;
      for (const p of allPatterns) {
        // Reset lastIndex for global patterns (none are global, but be safe).
        p.regex.lastIndex = 0;
        if (p.regex.test(line)) {
          findings.push({
            file: path.relative(root, file) || file,
            line: i + 1,
            rule: p.rule,
            severity: p.severity,
            snippet: redactSnippet(line),
          });
          break; // one finding per line is enough
        }
      }
      if (opts?.extraPatterns) {
        for (const re of opts.extraPatterns) {
          re.lastIndex = 0;
          if (re.test(line)) {
            findings.push({
              file: path.relative(root, file) || file,
              line: i + 1,
              rule: "custom",
              severity: "medium",
              snippet: redactSnippet(line),
            });
            break;
          }
        }
      }
    }
  }
  findings.sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line);
  const blocksPublish = findings.some((f) => {
    const p = allPatterns.find((x) => x.rule === f.rule);
    return p?.blocksPublish || f.severity === "critical";
  });
  return { findings, blocksPublish };
}

export function formatFindings(result: ScanResult): string {
  if (result.findings.length === 0)
    return "No secrets or dangerous patterns detected.";
  return result.findings
    .map((f) => `${f.severity} ${f.file}:${f.line} [${f.rule}]: ${f.snippet}`)
    .join("\n");
}
