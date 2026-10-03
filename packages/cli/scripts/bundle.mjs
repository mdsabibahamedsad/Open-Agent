// Bundle the CLI (and its workspace deps) into one self-contained file so the
// published npm package installs without workspace:* resolution.
import * as esbuild from "esbuild";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dir = path.dirname(fileURLToPath(import.meta.url));

await esbuild.build({
  entryPoints: [path.join(dir, "..", "src", "bin", "openagent.ts")],
  bundle: true,
  platform: "node",
  target: "node20",
  format: "cjs",
  outfile: path.join(dir, "..", "dist", "bin", "openagent.cjs"),
  logLevel: "warning",
});
console.log("bundled dist/bin/openagent.cjs");
