import { defineAgent } from "@openagent/extension-sdk";

// SSO/RBAC/allowlist notes:
// - Published to the private org registry only (visibility: organization).
// - Install requires SSO group `acme-platform` (RBAC resource agent:invoke).
// - VAULT token is a secret ref; egress allowlisted to vault.acme.example.
// - All runs audited per-actor; approvals required for secret:access.
export default defineAgent({
  name: "vault-agent",
  description: "Look up approved vault entries.",
  model: { default: "gpt-4o-mini" },
  systemPrompt: "Answer only from vault entries. Never reveal the token.",
  async onRun(ctx, input: { path: string }) {
    const entry = await ctx.tools.invoke("vault.read", { path: input.path });
    return { path: input.path, entry };
  },
});
