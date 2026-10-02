import { defineTool } from "@openagent/extension-sdk";

export default defineTool({
  name: "py.run",
  description: "Run a Python snippet in the sandbox (no network, 10s cap).",
  inputSchema: {
    type: "object",
    properties: { code: { type: "string", maxLength: 8000 } },
    required: ["code"],
  },
  outputSchema: { type: "object", properties: { stdout: { type: "string" } }, required: ["stdout"] },
  timeoutSeconds: 10,
  async handler(ctx, args: { code: string }) {
    if (/(__import__|import\s+os|import\s+sys|socket|subprocess)/.test(args.code)) {
      throw new Error("code uses forbidden modules");
    }
    // Executed inside the sandbox profile CODE_DEFAULT: non-root, no net,
    // structured argv ["python", "-c", code], artifacts via storage refs.
    return ctx.sandbox.execute({ language: "python", code: args.code, timeoutSeconds: 10 });
  },
});
