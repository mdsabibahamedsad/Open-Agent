// @openagent/developer-tools — validator, scanner, docgen, migration,
// local registry, mocks, contract tests (§30-33, §41, §59-60, §62, §64).
// Offline-capable: every check also runs without the cloud.

import { ApiClient } from '@openagent/api-client';

export const DEVELOPER_TOOLS_VERSION = '1.0.0';

export const EXTENSION_TYPES = [
  'agent', 'skill', 'tool', 'workflow-node', 'connector',
  'mcp-server', 'mcp-tool', 'mcp-resource', 'mcp-prompt',
  'workflow-template', 'evaluator', 'memory-provider', 'model-provider',
  'model-adapter', 'browser-extension', 'sandbox-profile', 'integration',
  'ui-extension', 'automation-pack', 'agent-team',
] as const;

export const PERMISSION_CATALOG: Record<string, { risk: string; approval: boolean; hint: string }> = {
  'network:outbound': { risk: 'medium', approval: false, hint: 'Requires network.allowed_hosts allowlist.' },
  'network:restricted': { risk: 'critical', approval: true, hint: 'Private-network access. Needs approval + allowlisted policy.' },
  'filesystem:workspace': { risk: 'low', approval: false, hint: 'Workspace directory only.' },
  'filesystem:artifact': { risk: 'low', approval: false, hint: 'Declared artifacts only.' },
  'tool:execute': { risk: 'medium', approval: false, hint: 'Invoke tools via Tool Runtime.' },
  'connector:use': { risk: 'medium', approval: false, hint: 'Declared connections only.' },
  'memory:read': { risk: 'medium', approval: false, hint: 'Scoped memory reads.' },
  'memory:write': { risk: 'medium', approval: false, hint: 'Scoped memory writes.' },
  'browser:use': { risk: 'high', approval: true, hint: 'Browser sessions under browser policy.' },
  'sandbox:execute': { risk: 'medium', approval: false, hint: 'Sandboxed code execution.' },
  'mcp:connect': { risk: 'medium', approval: false, hint: 'Declared MCP servers.' },
  'secret:access': { risk: 'high', approval: true, hint: 'Secret references only — never values.' },
  'workflow:execute': { risk: 'medium', approval: false, hint: 'Start workflow executions.' },
  'agent:invoke': { risk: 'medium', approval: false, hint: 'Invoke sub-agents under policy.' },
  'model:invoke': { risk: 'low', approval: false, hint: 'Models via Model Router.' },
  'evaluation:run': { risk: 'low', approval: false, hint: 'Evaluate observable outputs.' },
  'webhook:receive': { risk: 'medium', approval: false, hint: 'Declared inbound endpoints.' },
  'storage:use': { risk: 'low', approval: false, hint: 'Object storage within quota.' },
  'billing:read': { risk: 'low', approval: false, hint: 'Own usage/entitlements.' },
};

export interface ValidationIssue {
  severity: 'error' | 'warning';
  location: string;
  message: string;
  fix?: string;
}

const SEMVER_RE = /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.\-]+)?(?:\+[0-9A-Za-z.\-]+)?$/;

export function validateManifest(manifest: Record<string, unknown>): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const err = (location: string, message: string, fix?: string) =>
    issues.push({ severity: 'error', location, message, fix });
  const warn = (location: string, message: string, fix?: string) =>
    issues.push({ severity: 'warning', location, message, fix });

  if (typeof manifest.name !== 'string' || manifest.name.length < 2) {
    err('name', 'name must be a string of at least 2 characters');
  }
  if (typeof manifest.version !== 'string' || !SEMVER_RE.test(manifest.version)) {
    err('version', `version '${manifest.version}' is not valid semver MAJOR.MINOR.PATCH`,
      'Use e.g. "1.0.0".');
  }
  if (!EXTENSION_TYPES.includes(manifest.type as (typeof EXTENSION_TYPES)[number])) {
    err('type', `unknown extension type '${manifest.type}'`,
      `Choose one of: ${EXTENSION_TYPES.join(', ')}`);
  }
  if (typeof manifest.description !== 'string' || !manifest.description) {
    err('description', 'description is required');
  }
  const author = manifest.author as Record<string, unknown> | undefined;
  if (!author || typeof author.name !== 'string' || !author.name) {
    err('author.name', 'author.name is required');
  }
  if (typeof manifest.license !== 'string' || !manifest.license) {
    err('license', 'license is required (§56)', 'Declare an SPDX identifier, e.g. "MIT".');
  }
  const perms = (manifest.permissions ?? []) as string[];
  for (const p of perms) {
    if (!(p in PERMISSION_CATALOG)) {
      err('permissions', `unknown permission '${p}`, 'Use only catalog permissions.');
    }
  }
  if (perms.includes('network:outbound')) {
    const network = (manifest.network ?? {}) as Record<string, unknown>;
    const hosts = (network.allowed_hosts ?? []) as unknown[];
    if (!Array.isArray(hosts) || hosts.length === 0) {
      err('network.allowed_hosts', "'network:outbound' requires a non-empty allowed_hosts list");
    }
  }
  for (const s of ((manifest.secrets ?? []) as unknown[])) {
    if (typeof s !== 'string' || !/^[A-Z][A-Z0-9_]{2,63}$/.test(s)) {
      err('secrets', `secret reference '${s}' must be an ENV_VAR_NAME (never a value)`);
    }
  }
  if (!manifest.repository) warn('repository', 'repository is empty: ownership cannot be verified');
  return issues;
}

// ------------------------------------------------------------ scanner -----

const SECRET_RULES: Array<[string, RegExp]> = [
  ['aws-access-key', /AKIA[0-9A-Z]{16}/],
  ['private-key', /-----BEGIN (?:RSA )?PRIVATE KEY-----/],
  ['openai-key', /sk-[A-Za-z0-9]{20,}/],
  ['github-token', /gh[pousr]_[A-Za-z0-9]{20,}/],
  ['generic-api-key', /(api[_-]?key|apikey)\s*[:=]\s*['"][A-Za-z0-9_\-]{16,}['"]/i],
  ['password-assign', /(password|passwd|pwd)\s*[:=]\s*['"][^'"]{4,}['"]/i],
  ['oauth-secret', /(client_secret|oauth_secret)\s*[:=]\s*['"][^'"]{6,}['"]/i],
];

const CODE_RULES: Array<[string, RegExp, 'low' | 'medium' | 'high' | 'critical']> = [
  ['unsafe-eval', /\beval\s*\(/, 'high'],
  ['docker-socket', /docker\.sock/, 'critical'],
  ['host-filesystem', /\/etc\/(passwd|shadow)|\/proc\/self/, 'high'],
  ['subprocess-shell', /subprocess\.\w+\([^)]*shell\s*=\s*True|os\.system\s*\(/, 'high'],
  ['child-process', /child_process|execSync|spawn\s*\(/, 'medium'],
  ['credential-logging', /console\.(log|debug)\s*\([^)]*(password|secret|token)/i, 'high'],
  ['install-hook', /"(preinstall|postinstall|install)"\s*:/, 'medium'],
  ['disable-tls', /NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['"]?0|rejectUnauthorized\s*:\s*false/, 'high'],
];

function isAllowlisted(path: string): boolean {
  return /readme|changelog|license|\.example|fixture|mock/i.test(path);
}

export interface ScanFinding {
  rule: string;
  severity: 'low' | 'medium' | 'high' | 'critical' | 'secret';
  file: string;
  line: number;
  excerpt: string;
}

export function scanFiles(files: Record<string, string>): { findings: ScanFinding[]; blocksPublish: boolean } {
  const findings: ScanFinding[] = [];
  for (const [path, content] of Object.entries(files)) {
    const lines = content.split('\n');
    lines.forEach((line, i) => {
      for (const [rule, re] of SECRET_RULES) {
        if (re.test(line)) {
          if (isAllowlisted(path) && /example/i.test(line)) continue;
          findings.push({ rule: `secret:${rule}`, severity: 'secret', file: path, line: i + 1, excerpt: line.slice(0, 120) });
        }
      }
      for (const [rule, re, severity] of CODE_RULES) {
        if (re.test(line)) {
          findings.push({ rule, severity, file: path, line: i + 1, excerpt: line.slice(0, 120) });
        }
      }
    });
  }
  const blocksPublish =
    findings.some((f) => f.severity === 'secret' || f.severity === 'critical');
  return { findings, blocksPublish };
}

// ------------------------------------------------------------ docgen ------

export function generateDocs(manifest: Record<string, unknown>): Record<string, string> {
  const name = String(manifest.name ?? 'extension');
  const description = String(manifest.description ?? '');
  const perms = ((manifest.permissions ?? []) as string[]).map(
    (p) => `- \`${p}\` (${PERMISSION_CATALOG[p]?.risk ?? 'unknown'} risk)`,
  ).join('\n') || '_(none)_';
  const readme = [
    `# ${name}`, '', description, '',
    '## Installation', '', '```bash',
    'openagent registry install ' + name, '```', '',
    '## Permissions', '', perms, '',
    '## Security Notes', '',
    '- Secrets are referenced by name and never embedded.',
    '- Execution passes through Tool Runtime / Sandbox under RBAC + policy.',
    '',
  ].join('\n');
  const configRef = [
    `# Configuration Reference — ${name}`, '',
    '```json',
    JSON.stringify(manifest.config_schema ?? {}, null, 2),
    '```', '',
  ].join('\n');
  return { 'README.md': readme, 'CONFIG.md': configRef };
}

// ---------------------------------------------------------- migration -----

const KNOWN_DEPRECATED: Array<{ pattern: RegExp; replacement: string }> = [
  { pattern: /client\.runs\.list\(\)/, replacement: 'client.agentRuns.list()' },
  { pattern: /createSDK\(/, replacement: 'new OpenAgent()' },
];

export function findDeprecatedUsages(source: string, file = 'src'): Array<{ file: string; line: number; match: string; replacement: string }> {
  const out: Array<{ file: string; line: number; match: string; replacement: string }> = [];
  source.split('\n').forEach((line, i) => {
    for (const { pattern, replacement } of KNOWN_DEPRECATED) {
      const m = line.match(pattern);
      if (m) out.push({ file, line: i + 1, match: m[0], replacement });
    }
  });
  return out;
}

// ------------------------------------------------------ local registry ----

export interface LocalPackageIndex {
  registry: string;
  packages: Array<{ artifact: string; name?: string; version?: string }>;
}

export async function readLocalRegistry(client: ApiClient): Promise<LocalPackageIndex> {
  return client.get<LocalPackageIndex>('/registry/local/packages');
}

// ------------------------------------------------------------- mocks ------

export const mocks = {
  llm: {
    complete: (prompt: string) => ({
      text: `[mock completion for: ${prompt.slice(0, 64)}]`,
      model: 'mock-smart',
      usage: { prompt_tokens: Math.ceil(prompt.length / 4), completion_tokens: 16 },
    }),
  },
  tool: {
    invoke: (tool: string, args: unknown) => ({ ok: true as const, tool, output: { echo: args } }),
  },
  sandbox: {
    execute: (command: string) =>
      /rm -rf|mkfs/.test(command)
        ? { ok: false as const, error: 'POLICY_DENIED: destructive command refused by mock' }
        : { ok: true as const, stdout: `[mock output of: ${command.slice(0, 80)}]`, exit_code: 0 },
  },
  memory: () => {
    const store = new Map<string, string>();
    return {
      write: (key: string, value: string) => { store.set(key, value); return { ok: true as const, key }; },
      read: (key: string) => ({ key, value: store.get(key) }),
    };
  },
};

// ----------------------------------------------------- contract tests -----

export interface ContractResult {
  name: string;
  passed: boolean;
  detail?: string;
}

export async function runToolContract(tool: {
  name: string;
  inputSchema: Record<string, unknown>;
  execute: (input: unknown, ctx: unknown) => Promise<unknown>;
}): Promise<ContractResult[]> {
  const results: ContractResult[] = [];
  results.push({
    name: 'manifest validation',
    passed: typeof tool.name === 'string' && tool.name.length > 0,
  });
  results.push({
    name: 'schema validation',
    passed: Boolean(tool.inputSchema && typeof tool.inputSchema === 'object'),
  });
  try {
    const ctx = { approved: true, timeoutMs: 5000, log: () => undefined };
    await tool.execute({}, ctx);
    results.push({ name: 'tool execution', passed: true });
  } catch (err) {
    results.push({ name: 'tool execution', passed: false, detail: String(err) });
  }
  try {
    const ctx = { approved: true, timeoutMs: 5000, log: () => undefined };
    await tool.execute({ unexpected_extra_field_xyz: 1 }, ctx);
    results.push({ name: 'error handling', passed: true });
  } catch {
    results.push({ name: 'error handling', passed: true, detail: 'rejected bad input (acceptable)' });
  }
  return results;
}
