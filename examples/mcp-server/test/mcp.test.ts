import { describe, expect, it } from "vitest";
import server from "../src/index.js";

describe("kb-server", () => {
  it("searches + reads + renders", async () => {
    const search = (server as any).tools.find((t: any) => t.name === "kb.search");
    expect(await search.handler({}, { q: "ssrf" })).toEqual({ hits: [{ id: "ssrf" }] });
    const read = (server as any).resources[0];
    expect((await read.read({}, { id: "secrets" })).mimeType).toBe("text/markdown");
    const prompt = (server as any).prompts[0];
    expect((await prompt.render({}, { id: "ssrf" }))[0].role).toBe("user");
  });
});
