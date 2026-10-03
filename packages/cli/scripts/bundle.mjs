// Bundle the CLI (and its workspace deps) into one self-contained file so the
// published npm package installs without workspace:* resolution.
import * as esbuild from "esbuild";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dir = path.dirname(fileURLToPath(import.meta.url));

const outFile = path.join(dir, "..", "dist", "bin", "openagent.cjs");

await esbuild.build({
  entryPoints: [path.join(dir, "..", "src", "bin", "openagent.ts")],
  bundle: true,
  platform: "node",
  target: "node20",
  format: "cjs",
  outfile: outFile,
  // Preserve the #!/usr/bin/env node shebang through bundling so npm's
  // Windows shim (.cmd/.ps1) and POSIX exec both work.
  banner: { js: "#!/usr/bin/env node" },
  logLevel: "warning",
});

// esbuild may emit a duplicate shebang or none depending on version —
// normalize to exactly one, then mark executable (POSIX; harmless on win32).
import fs from "node:fs";
let text = fs.readFileSync(outFile, "utf8");
text = text.replace(/^(#![^\n]*\n)+/, "");
fs.writeFileSync(outFile, `#!/usr/bin/env node\n${text}`);
try {
  fs.chmodSync(outFile, 0o755);
} catch {
  // Windows: chmod is best-effort.
}
try {
  fs.chmodSync(path.join(dir, "..", "bin", "openagent.js"), 0o755);
} catch {
  // Windows: chmod is best-effort.
}
console.log("bundled dist/bin/openagent.cjs");
