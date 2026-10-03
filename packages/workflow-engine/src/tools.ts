import type { ExecutionContext, ToolDefinition } from "./types.js";

export interface ToolHandler {
  definition: ToolDefinition;
  run: (input: unknown, ctx: ExecutionContext) => Promise<unknown>;
}

export type PermissionDecision = "allow" | "ask" | "deny";

/** Registry of callable tools (workflow nodes + MCP tools + custom tools). */
export class ToolRegistry {
  private handlers = new Map<string, ToolHandler>();
  private permissions = new Map<string, PermissionDecision>();

  register(
    handler: ToolHandler,
    permission: PermissionDecision = "allow",
  ): void {
    this.handlers.set(handler.definition.name, handler);
    this.permissions.set(handler.definition.name, permission);
  }

  setPermission(name: string, decision: PermissionDecision): void {
    this.permissions.set(name, decision);
  }

  permissionFor(name: string): PermissionDecision {
    return this.permissions.get(name) ?? "allow";
  }

  list(): ToolDefinition[] {
    return [...this.handlers.values()].map((h) => h.definition);
  }

  async execute(
    name: string,
    input: unknown,
    ctx?: ExecutionContext,
  ): Promise<unknown> {
    const h = this.handlers.get(name);
    if (!h) throw new Error(`unknown tool '${name}'`);
    const perm = this.permissionFor(name);
    if (perm === "deny") throw new Error(`tool '${name}' is denied by policy`);
    if (perm === "ask" && process.env.OPENAGENT_AUTO_APPROVE !== "1") {
      throw new Error(
        `tool '${name}' requires human approval (set permission to allow or OPENAGENT_AUTO_APPROVE=1)`,
      );
    }
    if (!ctx) throw new Error(`tool '${name}' needs an execution context`);
    return h.run(input, ctx);
  }
}
