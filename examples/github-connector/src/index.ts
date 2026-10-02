import { defineConnector } from "@openagent/extension-sdk";

export default defineConnector({
  id: "github-custom",
  displayName: "GitHub (custom)",
  // OAuth2 with PKCE via the platform OAuth manager. Tokens stay in the
  // Fernet credential store; we only ever hold a credential_ref handle.
  auth: { type: "oauth2", scopes: ["repo:read"], pkce: true },
  capabilities: [{ id: "github-custom.repos.read", risk: "LOW" }],
  actions: [
    {
      id: "github-custom.list_repos",
      inputSchema: {
        type: "object",
        properties: { org: { type: "string", minLength: 1 } },
        required: ["org"],
      },
      requiredCapabilities: ["github-custom.repos.read"],
      idempotent: true,
      timeoutSeconds: 20,
      async run(ctx, args: { org: string }) {
        const repos = await ctx.http.get(`https://api.github.com/orgs/${args.org}/repos`, {
          credentialRef: ctx.credentials.github,
        });
        return {
          repos: (repos as any[]).map((r) => ({ name: r.name, stars: r.stargazers_count })),
        };
      },
    },
  ],
  triggers: [{ id: "github-custom.push", kind: "webhook", eventTypes: ["push"] }],
});
