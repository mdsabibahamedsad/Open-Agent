import fs from "node:fs";
import path from "node:path";
import type { ExtensionType } from "./validate.js";

export type ScaffoldLanguage = "ts" | "python";
export type ScaffoldKind =
  | "agent"
  | "tool"
  | "workflow-node"
  | "connector"
  | "mcp-server"
  | "skill"
  | "workflow-template"
  | "evaluator"
  | "model-provider"
  | "full-extension";

export interface ScaffoldOptions {
  name: string;
  kind: ScaffoldKind | ExtensionType | string;
  language: ScaffoldLanguage;
  targetDir: string;
  description?: string;
}

const KIND_DESCRIPTIONS: Record<string, string> = {
  agent: "Autonomous agent extension",
  tool: "Reusable tool extension",
  "workflow-node": "Custom workflow node",
  connector: "Third-party connector",
  "mcp-server": "Model Context Protocol server",
  skill: "Reusable skill",
  "workflow-template": "Workflow template",
  evaluator: "Quality evaluator",
  "model-provider": "Model provider adapter",
  "full-extension": "Full extension bundle",
};

function sanitizeName(name: string): string {
  return name.trim().toLowerCase().replace(/[^a-z0-9-_]/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "") || "my-extension";
}

function manifestYaml(opts: Required<Pick<ScaffoldOptions, "name" | "kind" | "language" | "description">>): string {
  const entry = opts.language === "python" ? "src/main.py" : "src/index.ts";
  // Scaffold aliases map to canonical manifest types (backend registry).
  const manifestType = opts.kind === "full-extension" ? "automation-pack" : opts.kind;
  return [
    `manifest_version: '1'`,
    `name: ${opts.name}`,
    `version: '0.1.0'`,
    `type: ${manifestType}`,
    `description: ${JSON.stringify(opts.description)}`,
    `license: MIT`,
    `author:`,
    `  name: Your Name`,
    `runtime:`,
    `  entrypoint: ${entry}`,
    `  language: ${opts.language === "python" ? "python" : "typescript"}`,
    opts.language === "python" ? `  python: '>=3.10'` : `  node: '>=20.0.0'`,
    `permissions:`,
    `  - tool:execute`,
    `  - filesystem:workspace`,
    `  - model:invoke`,
    `compatibility:`,
    `  openagent: '>=1.0.0 <2.0.0'`,
    ``,
  ].join("\n");
}

function tsEntry(kind: string, name: string): string {
  return `// ${name} — ${kind} extension entrypoint.
// Minimal extension-sdk-style builder (self-contained, no external deps).

export interface ExtensionContext {
  log(message: string): void;
  config: Record<string, unknown>;
}

export interface ExtensionDefinition {
  name: string;
  kind: string;
  version: string;
  description: string;
  run(ctx: ExtensionContext, input: unknown): Promise<unknown>;
}

function defineExtension(def: ExtensionDefinition): ExtensionDefinition {
  return def;
}

export const extension = defineExtension({
  name: ${JSON.stringify(name)},
  kind: ${JSON.stringify(kind)},
  version: "0.1.0",
  description: "Hello-world OpenAgent extension.",
  async run(ctx, input) {
    ctx.log("Hello from ${name}!");
    return { ok: true, echo: input ?? null };
  },
});

export default extension;
`;
}

function pyEntry(kind: string, name: string): string {
  return `"""${name} — ${kind} extension entrypoint."""
from dataclasses import dataclass
from typing import Any


@dataclass
class ExtensionContext:
    config: dict

    def log(self, message: str) -> None:
        print(message)


def define_extension(name: str, kind: str, version: str, description: str, handler):
    return {
        "name": name,
        "kind": kind,
        "version": version,
        "description": description,
        "handler": handler,
    }


def handler(ctx: ExtensionContext, payload: Any) -> dict:
    ctx.log("Hello from ${name}!")
    return {"ok": True, "echo": payload}


extension = define_extension(
    ${JSON.stringify(name)},
    ${JSON.stringify(kind)},
    "0.1.0",
    "Hello-world OpenAgent extension.",
    handler,
)
`;
}

export function scaffoldProject(opts: ScaffoldOptions): { dir: string; files: string[] } {
  const name = sanitizeName(opts.name);
  const kind = String(opts.kind);
  const language = opts.language;
  const dir = path.resolve(opts.targetDir, name);
  if (fs.existsSync(dir) && fs.readdirSync(dir).length > 0) {
    throw new Error(`Target directory ${dir} already exists and is not empty.`);
  }
  const files: string[] = [];
  const write = (rel: string, content: string) => {
    const full = path.join(dir, rel);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, content);
    files.push(rel);
  };
  const kindDesc = KIND_DESCRIPTIONS[kind] ?? "OpenAgent extension";
  const description = opts.description?.trim() || `${kindDesc} named ${name}.`;

  write("openagent.yaml", manifestYaml({ name, kind, language, description }));
  if (language === "ts") {
    write("src/index.ts", tsEntry(kind, name));
    write(
      "package.json",
      JSON.stringify({ name: `@openagent-ext/${name}`, version: "0.1.0", private: true, type: "module", main: "src/index.ts", scripts: { build: "tsc -p tsconfig.json", test: "node --test" } }, null, 2) + "\n",
    );
    write(
      "tsconfig.json",
      JSON.stringify({ compilerOptions: { target: "ES2022", module: "NodeNext", moduleResolution: "NodeNext", strict: true, outDir: "dist", rootDir: "src", skipLibCheck: true }, include: ["src/**/*"] }, null, 2) + "\n",
    );
    write("tests/hello.test.ts", `import assert from "node:assert/strict";\nimport { extension } from "../src/index.js";\n\nconst ctx = { log() {}, config: {} };\nconst out = (await extension.run(ctx, { hello: "world" })) as Record<string, unknown>;\nassert.equal(out.ok, true);\n`);
  } else {
    write("src/main.py", pyEntry(kind, name));
    write("src/__init__.py", `"""${name} package."""\n`);
    write("pyproject.toml", `[project]\nname = "${name}"\nversion = "0.1.0"\ndescription = ${JSON.stringify(description)}\nrequires-python = ">=3.10"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n`);
    write("tests/test_hello.py", `from src.main import extension\n\n\ndef test_hello():\n    handler = extension["handler"]\n    from src.main import ExtensionContext\n    out = handler(ExtensionContext(config={}), {"hello": "world"})\n    assert out["ok"] is True\n`);
    write("requirements.txt", `# add runtime dependencies here\n`);
  }
  write("examples/basic.json", JSON.stringify({ input: { hello: "world" }, expected: { ok: true } }, null, 2) + "\n");
  write("docs/OVERVIEW.md", `# ${name}\n\n${description}\n\nKind: \`${kind}\`\n\n## Development\n\n- \`openagent validate\` — offline manifest validation\n- \`openagent test\` — offline checks + server tests\n- \`openagent package\` — build deterministic \`.oaext\`\n`);
  write("README.md", `# ${name}\n\n${description}\n\n## Quickstart\n\n\`\`\`bash\nopenagent validate\nopenagent package\nopenagent publish --version 0.1.0\n\`\`\`\n`);
  write(".gitignore", "node_modules/\ndist/\n*.oaext\n.env\n__pycache__/\n.venv/\n");
  write("Dockerfile", `FROM node:20-slim\nWORKDIR /app\nCOPY . .\nCMD ["node", "--version"]\n`);
  return { dir, files: files.sort() };
}

export const SCAFFOLD_KINDS = [
  "agent",
  "tool",
  "workflow-node",
  "connector",
  "mcp-server",
  "skill",
  "workflow-template",
  "evaluator",
  "model-provider",
  "full-extension",
] as const;
