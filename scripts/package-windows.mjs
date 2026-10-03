// Builds Windows install artifacts:
//   dist/openagent-win-x64.zip        (portable app incl. prod node_modules)
//   dist/windows-nsis/OpenAgent/      (NSIS staging incl. payload zip)
//   dist/OpenAgent-Setup.exe          (only when `makensis` is available)
// Usage: npm run package:windows
import { execFileSync, execSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const pkg = JSON.parse(
  fs.readFileSync(path.join(root, "package.json"), "utf8"),
);
const version = pkg.version ?? "0.1.0";

function sh(cmd, opts = {}) {
  console.log(`> ${cmd}`);
  execSync(cmd, { stdio: "inherit", cwd: root, shell: false, ...opts });
}

function sha256(file) {
  const h = crypto.createHash("sha256");
  h.update(fs.readFileSync(file));
  return h.digest("hex");
}

// 1. Self-contained CLI tree (prod deps only) via pnpm deploy.
const deployDir = path.join(dist, "windows-portable", "app", "cli");
fs.rmSync(path.join(dist, "windows-portable"), {
  recursive: true,
  force: true,
});
fs.mkdirSync(deployDir, { recursive: true });
sh(`pnpm --filter @openagent/cli --prod deploy "${deployDir}"`);
repairDeployedTree(deployDir);
smokeTestCli(deployDir);

/**
 * pnpm deploy materializes symlinks as plain directories on Windows, which
 * breaks nested transitive resolution (e.g. prompts -> kleur). Repair by
 * hoisting first-seen nested packages to the top level (npm-style flat tree).
 * Only fills names missing at top level, so direct versions never change.
 */
function repairDeployedTree(cliDir) {
  const top = path.join(cliDir, "node_modules");
  const pnpmDir = path.join(top, ".pnpm");
  if (!fs.existsSync(pnpmDir)) return;
  const have = new Set(fs.readdirSync(top));
  let hoisted = 0;
  for (const entry of fs.readdirSync(pnpmDir)) {
    if (entry.startsWith("file+")) continue;
    const nested = path.join(pnpmDir, entry, "node_modules");
    if (!fs.existsSync(nested)) continue;
    for (const name of fs.readdirSync(nested)) {
      if (name.startsWith(".")) continue;
      if (name.startsWith("@")) {
        const scopeDir = path.join(top, name);
        for (const sub of fs.readdirSync(path.join(nested, name))) {
          if (have.has(name) && fs.existsSync(path.join(scopeDir, sub)))
            continue;
          fs.mkdirSync(scopeDir, { recursive: true });
          fs.cpSync(path.join(nested, name, sub), path.join(scopeDir, sub), {
            recursive: true,
          });
          hoisted++;
        }
        have.add(name);
        continue;
      }
      if (have.has(name)) continue;
      fs.cpSync(path.join(nested, name), path.join(top, name), {
        recursive: true,
      });
      have.add(name);
      hoisted++;
    }
  }
  console.log(`hoisted ${hoisted} transitive package(s) into portable tree`);
}

function smokeTestCli(cliDir) {
  const bin = path.join(cliDir, "dist", "bin", "openagent.js");
  const out = execFileSync(process.execPath, [bin, "--version"], {
    encoding: "utf8",
    timeout: 60000,
  }).trim();
  console.log(`portable CLI smoke test: openagent ${out}`);
  if (!/^\d+\.\d+\.\d+/.test(out))
    throw new Error("portable CLI smoke test failed");
}

// 2. Portable layout: <root>/app/cli + bin shim + installer scripts.
const portable = path.join(dist, "windows-portable", "OpenAgent");
fs.rmSync(portable, { recursive: true, force: true });
fs.mkdirSync(portable, { recursive: true });
fs.cpSync(deployDir, path.join(portable, "app", "cli"), { recursive: true });
fs.cpSync(
  path.join(root, "tools", "installer", "windows"),
  path.join(portable, "tools", "installer", "windows"),
  {
    recursive: true,
  },
);
const shim = `@echo off\r\nsetlocal\r\nset OA_NODE=%~dp0..\\runtime\\node\\node.exe\r\nif not exist "%OA_NODE%" set OA_NODE=node\r\n"%OA_NODE%" "%~dp0..\\app\\cli\\dist\\bin\\openagent.js" %*\r\n`;
fs.mkdirSync(path.join(portable, "bin"), { recursive: true });
fs.writeFileSync(path.join(portable, "bin", "openagent.cmd"), shim);
fs.writeFileSync(
  path.join(portable, "VERSION"),
  `openagent ${version} (windows-x64 portable, built ${new Date().toISOString()})\n`,
);

// 3. Zip the portable tree (PowerShell on Windows, `zip` elsewhere).
const zipPath = path.join(dist, "openagent-win-x64.zip");
fs.rmSync(zipPath, { force: true });
if (process.platform === "win32") {
  execFileSync(
    "powershell.exe",
    [
      "-NoProfile",
      "-Command",
      `Compress-Archive -LiteralPath '${portable}' -DestinationPath '${zipPath}' -Force`,
    ],
    { stdio: "inherit" },
  );
} else {
  execSync(`zip -qr "${zipPath}" OpenAgent`, {
    stdio: "inherit",
    cwd: path.join(dist, "windows-portable"),
  });
}
fs.writeFileSync(
  `${zipPath}.sha256`,
  `${sha256(zipPath)}  openagent-win-x64.zip\n`,
);
console.log(
  `wrote ${zipPath} (${(fs.statSync(zipPath).size / 1048576).toFixed(1)} MB)`,
);

// 4. NSIS staging.
const nsis = path.join(dist, "windows-nsis", "OpenAgent");
fs.rmSync(path.join(dist, "windows-nsis"), { recursive: true, force: true });
fs.mkdirSync(path.join(nsis, "payload"), { recursive: true });
fs.mkdirSync(path.join(nsis, "tools", "installer", "windows"), {
  recursive: true,
});
fs.copyFileSync(zipPath, path.join(nsis, "payload", "openagent-win-x64.zip"));
fs.copyFileSync(
  `${zipPath}.sha256`,
  path.join(nsis, "payload", "openagent-win-x64.zip.sha256"),
);
for (const f of ["Install-OpenAgent.ps1", "Uninstall-OpenAgent.ps1"]) {
  fs.copyFileSync(
    path.join(root, "tools", "installer", "windows", f),
    path.join(nsis, "tools", "installer", "windows", f),
  );
}
console.log(`NSIS staging ready at ${nsis}`);

// 5. OpenAgent-Setup.exe when NSIS is available (CI); otherwise instructions.
let makensis = null;
try {
  execSync(process.platform === "win32" ? "where makensis" : "which makensis", {
    stdio: "pipe",
  });
  makensis = true;
} catch {
  makensis = false;
}
if (makensis) {
  sh(
    `makensis "${path.join(root, "tools", "installer", "windows", "installer.nsi")}"`,
  );
  console.log("built dist/OpenAgent-Setup.exe");
} else {
  console.log(
    "makensis not found — install NSIS and run: makensis tools/installer/windows/installer.nsi",
  );
}
