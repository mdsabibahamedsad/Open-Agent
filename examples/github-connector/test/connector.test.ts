import { describe, expect, it } from "vitest";
import connector from "../src/index.js";

describe("github-custom", () => {
  it("lists repos via guarded http", async () => {
    const ctx: any = {
      credentials: { github: "cred_123" },
      http: { get: async () => [{ name: "oa", stargazers_count: 7 }] },
    };
    const action = (connector as any).actions.find((a: any) => a.id === "github-custom.list_repos");
    expect(await action.run(ctx, { org: "my-org" })).toEqual({ repos: [{ name: "oa", stars: 7 }] });
  });
});
