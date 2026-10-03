import { describe, expect, it } from "vitest";
import {
  cliNotFoundMessage,
  getNpmGlobalInfo,
  type NpmGlobalInfo,
} from "./local.js";

describe("npm global install diagnostics", () => {
  it("reports prefix, expected exe and PATH containment", async () => {
    const info = await getNpmGlobalInfo();
    expect(typeof info.prefix).toBe("string");
    expect(info.prefix.length).toBeGreaterThan(0);
    expect(info.binDir.length).toBeGreaterThan(0);
    expect(info.expectedExe.toLowerCase()).toContain("openagent");
    expect(typeof info.exeExists).toBe("boolean");
    expect(typeof info.pathContainsBin).toBe("boolean");
    if (process.platform === "win32") {
      expect(info.expectedExe.endsWith("openagent.cmd")).toBe(true);
      expect(info.binDir).toBe(info.prefix);
    }
  });

  it("explains the placeholder collision and the official package", () => {
    const info: NpmGlobalInfo = {
      npmVersion: "11.0.0",
      prefix: "C:\\Users\\User\\.npm-global",
      binDir: "C:\\Users\\User\\.npm-global",
      expectedExe: "C:\\Users\\User\\.npm-global\\openagent.cmd",
      exeExists: false,
      pathContainsBin: true,
      installDir: null,
    };
    const msg = cliNotFoundMessage(info);
    expect(msg).toContain("npm install -g @openagent/cli");
    expect(msg).toContain("npx @openagent/cli --help");
    expect(msg).toContain("restart your terminal");
  });

  it("calls out installed-but-not-on-PATH", () => {
    const info: NpmGlobalInfo = {
      npmVersion: "11.0.0",
      prefix: "C:\\Users\\User\\.npm-global",
      binDir: "C:\\Users\\User\\.npm-global",
      expectedExe: "C:\\Users\\User\\.npm-global\\openagent.cmd",
      exeExists: true,
      pathContainsBin: false,
      installDir: "C:\\Users\\User\\.npm-global\\node_modules\\@openagent\\cli",
    };
    expect(cliNotFoundMessage(info)).toContain(
      "OpenAgent CLI is installed but Windows cannot find it from PATH",
    );
  });
});
