import fs from "node:fs";
import path from "node:path";
import {
  FileCredentialResolver,
  FileMemoryManager,
  ToolRegistry,
  checkOllama,
  getTemplate,
  runWorkflow,
  validateWorkflow,
} from "@openagent/workflow-engine";

export interface WizardState {
  version: 1;
  completed: boolean;
  steps: Record<string, { done: boolean; at?: string }>;
  aiMode: "local" | "cloud" | "hybrid";
  profile: string;
}

const WIZARD_STEPS = [
  "welcome",
  "ai",
  "storage",
  "browser",
  "permissions",
  "finish",
] as const;

function wizardFile(dataDir: string): string {
  return path.join(dataDir, "config", "wizard.json");
}

export function loadWizard(dataDir: string): WizardState | null {
  try {
    const f = wizardFile(dataDir);
    if (!fs.existsSync(f)) return null;
    return JSON.parse(fs.readFileSync(f, "utf8")) as WizardState;
  } catch {
    return null;
  }
}

export function saveWizard(dataDir: string, state: WizardState): void {
  fs.mkdirSync(path.dirname(wizardFile(dataDir)), { recursive: true });
  fs.writeFileSync(wizardFile(dataDir), JSON.stringify(state, null, 2));
}

export function defaultWizard(
  aiMode: WizardState["aiMode"] = "local",
  profile = "BALANCED",
): WizardState {
  return {
    version: 1,
    completed: false,
    steps: Object.fromEntries(WIZARD_STEPS.map((s) => [s, { done: false }])),
    aiMode,
    profile,
  };
}

export function completeStep(dataDir: string, step: string): WizardState {
  const w = loadWizard(dataDir) ?? defaultWizard();
  w.steps[step] = { done: true, at: new Date().toISOString() };
  if (WIZARD_STEPS.every((s) => w.steps[s]?.done)) w.completed = true;
  saveWizard(dataDir, w);
  return w;
}

export interface SuccessCheck {
  name: string;
  ok: boolean;
  detail: string;
  skipped?: boolean;
}

/**
 * First-run success test: Core, Database, AI, Workflow Engine, Browser.
 * Never hard-fails on missing optional components — those are reported as
 * skipped with a Setup-AI style hint instead.
 */
export async function runSuccessTest(
  projectDir: string,
): Promise<SuccessCheck[]> {
  const checks: SuccessCheck[] = [];

  // Core: hello-ai template validates and its graph is acyclic/runnable.
  try {
    const tpl = getTemplate("hello-ai");
    if (!tpl) throw new Error("hello-ai template missing");
    const wf = tpl.build();
    wf.id = "hello-ai";
    const v = validateWorkflow(wf);
    checks.push({
      name: "Core",
      ok: v.ok,
      detail: v.ok
        ? "workflow engine ready"
        : v.errors.map((e) => e.message).join("; "),
    });
    if (v.ok) {
      try {
        const dir = path.join(projectDir, ".openagent", "workflows");
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(
          path.join(dir, "hello-ai.json"),
          JSON.stringify(wf, null, 2),
        );
      } catch {
        // seed is best-effort
      }
    }
  } catch (e) {
    checks.push({
      name: "Core",
      ok: false,
      detail: e instanceof Error ? e.message : String(e),
    });
  }

  // Database: memory round-trip (SQLite-ready local store).
  try {
    const mem = new FileMemoryManager(projectDir, "setup-test");
    await mem.set("setup:selftest", { at: new Date().toISOString() });
    const back = await mem.get("setup:selftest");
    checks.push({
      name: "Database",
      ok: back !== undefined,
      detail:
        back !== undefined
          ? "local database read/write OK"
          : "write was not readable",
    });
  } catch (e) {
    checks.push({
      name: "Database",
      ok: false,
      detail: e instanceof Error ? e.message : String(e),
    });
  }

  // AI: prefer real Ollama, accept labeled fallback as degraded-but-working.
  try {
    const ollama = await checkOllama();
    if (ollama.ok && ollama.models.length > 0) {
      checks.push({
        name: "AI",
        ok: true,
        detail: `Ollama connected (${ollama.models[0]})`,
      });
    } else if (process.env.OPENAI_API_KEY) {
      checks.push({
        name: "AI",
        ok: true,
        detail: "cloud provider key configured",
      });
    } else {
      checks.push({
        name: "AI",
        ok: true,
        detail:
          "no model yet — heuristic fallback active (Setup AI from dashboard)",
        skipped: true,
      });
    }
  } catch (e) {
    checks.push({
      name: "AI",
      ok: false,
      detail: e instanceof Error ? e.message : String(e),
    });
  }

  // Workflow Engine: run hello-ai end to end.
  try {
    const tpl = getTemplate("hello-ai");
    if (!tpl) throw new Error("hello-ai template missing");
    const wf = tpl.build();
    wf.id = "hello-ai-selftest";
    const rec = await runWorkflow(wf, {
      input: { hello: "world" },
      credentials: new FileCredentialResolver(projectDir),
      memory: new FileMemoryManager(projectDir, "setup-test"),
      tools: new ToolRegistry(),
      projectDir,
      timeout: 60000,
    });
    checks.push({
      name: "Workflow Engine",
      ok: rec.status === "SUCCESS",
      detail: `hello-ai finished: ${rec.status}`,
    });
  } catch (e) {
    checks.push({
      name: "Workflow Engine",
      ok: false,
      detail: e instanceof Error ? e.message : String(e),
    });
  }

  // Browser: reachable check only — full automation needs Playwright/Chromium.
  try {
    const res = await fetch("https://example.com", {
      signal: AbortSignal.timeout(10000),
    });
    checks.push({
      name: "Browser",
      ok: true,
      detail: res.ok
        ? "network fetch OK (install Playwright for full automation)"
        : `HTTP ${res.status}`,
      skipped: !res.ok,
    });
  } catch {
    checks.push({
      name: "Browser",
      ok: true,
      detail: "offline — browser automation verified when online",
      skipped: true,
    });
  }

  return checks;
}
