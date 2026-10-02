import { describe, expect, it } from "vitest";
import mod from "../src/index.js";

describe("hello-world", () => {
  it("loads", () => {
    expect(mod).toBeDefined();
  });
});
