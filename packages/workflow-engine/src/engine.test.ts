import { describe, expect, it } from "vitest";
import { runWorkflow } from "./engine.js";
import { validateWorkflow } from "./schema.js";
import { generateWorkflowFromPrompt } from "./templates.js";
import { parseIntervalToMs, cronDue } from "./scheduler.js";
import { InMemoryMemoryManager } from "./memory.js";
import type { WorkflowDefinition } from "./types.js";

const LINEAR: WorkflowDefinition = {
  id: "wf_test",
  name: "Test",
  version: 1,
  nodes: [
    { id: "trigger", type: "manual", position: { x: 0, y: 0 }, config: {} },
    {
      id: "t",
      type: "transform",
      position: { x: 1, y: 0 },
      config: { template: { hello: "{{input.name}}" } },
    },
  ],
  edges: [{ source: "trigger", target: "t" }],
};

describe("workflow schema", () => {
  it("accepts a valid workflow", () => {
    expect(validateWorkflow(LINEAR).ok).toBe(true);
  });
  it("rejects cycles", () => {
    const cyclic: WorkflowDefinition = {
      ...LINEAR,
      edges: [
        { source: "trigger", target: "t" },
        { source: "t", target: "trigger" },
      ],
    };
    expect(validateWorkflow(cyclic).ok).toBe(false);
  });
});

describe("workflow engine", () => {
  it("runs a linear workflow", async () => {
    const rec = await runWorkflow(LINEAR, { input: { name: "ada" } });
    expect(rec.status).toBe("SUCCESS");
    expect(rec.outputs["t"]).toEqual({ hello: "ada" });
  });

  it("runs parallel branches and merges", async () => {
    const wf: WorkflowDefinition = {
      id: "wf_parallel",
      name: "Parallel",
      nodes: [
        { id: "start", type: "manual", position: { x: 0, y: 0 }, config: {} },
        {
          id: "b",
          type: "text",
          position: { x: 1, y: 0 },
          config: { text: "B" },
        },
        {
          id: "c",
          type: "text",
          position: { x: 1, y: 1 },
          config: { text: "C" },
        },
        { id: "m", type: "merge", position: { x: 2, y: 0 }, config: {} },
      ],
      edges: [
        { source: "start", target: "b" },
        { source: "start", target: "c" },
        { source: "b", target: "m" },
        { source: "c", target: "m" },
      ],
    };
    const rec = await runWorkflow(wf, { input: {} });
    expect(rec.status).toBe("SUCCESS");
    expect(rec.nodeStates["b"]?.status).toBe("SUCCESS");
    expect(rec.nodeStates["c"]?.status).toBe("SUCCESS");
  });

  it("retries then honors fallback policy", async () => {
    const wf: WorkflowDefinition = {
      id: "wf_retry",
      name: "Retry",
      nodes: [
        {
          id: "bad",
          type: "http",
          position: { x: 0, y: 0 },
          config: {},
          retry: { enabled: true, attempts: 2, delay: 1 },
          onError: "fallback",
          fallbackValue: { ok: false },
        },
      ],
      edges: [],
    };
    const rec = await runWorkflow(wf, { input: {} });
    expect(rec.status).toBe("SUCCESS");
    expect(rec.nodeStates["bad"]?.attempts).toBe(2);
  });

  it("supports memory nodes", async () => {
    const mem = new InMemoryMemoryManager();
    const wf: WorkflowDefinition = {
      id: "wf_mem",
      name: "Mem",
      nodes: [
        {
          id: "a",
          type: "text",
          position: { x: 0, y: 0 },
          config: { text: "remember me" },
        },
        {
          id: "w",
          type: "memory",
          position: { x: 1, y: 0 },
          config: { operation: "set", key: "k" },
        },
      ],
      edges: [{ source: "a", target: "w" }],
    };
    const rec = await runWorkflow(wf, { input: {}, memory: mem });
    expect(rec.status).toBe("SUCCESS");
    expect(await mem.get("k")).toBe("remember me");
  });
});

describe("generator + scheduler helpers", () => {
  it("generates a workflow from NL prompt", () => {
    const wf = generateWorkflowFromPrompt(
      "Every morning search AI news, summarize the top 5 stories and save it to a file.",
    );
    expect(wf.nodes.length).toBeGreaterThanOrEqual(3);
    expect(validateWorkflow(wf).ok).toBe(true);
  });
  it("parses intervals and cron", () => {
    expect(parseIntervalToMs("5m")).toBe(300000);
    expect(typeof cronDue("0 9 * * *")).toBe("boolean");
  });
});
