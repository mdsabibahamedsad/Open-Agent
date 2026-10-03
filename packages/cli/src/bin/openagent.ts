#!/usr/bin/env node
import { Command } from "commander";
import pc from "picocolors";
import { registerCommands } from "../commands.js";
import { registerLocalCommands, printWelcome } from "../localCommands.js";
import { findProjectDir } from "../local.js";
import { OpenAgentError } from "../http.js";

const program = new Command();

program
  .name("openagent")
  .description(
    "Production-grade OpenAgent CLI for extension development and lifecycle management",
  )
  .version("1.0.0", "--version", "Show CLI version")
  .option("--json", "machine-readable JSON output")
  .option("--quiet", "suppress human-readable output")
  .option("--verbose", "verbose request logging to stderr")
  .option("--org <orgId>", "organization ID override")
  .option("--profile <name>", "config profile name")
  .option("--no-color", "disable colored output");

registerCommands(program);
registerLocalCommands(program);

program.action(() => {
  if (!findProjectDir()) {
    printWelcome();
    return;
  }
  program.help();
});

program.showHelpAfterError("(add --help for usage)");

function exitCodeFor(err: unknown): number {
  if (err instanceof OpenAgentError) return err.exitCode;
  const e = err as { exitCode?: unknown; status?: unknown } | null;
  if (e && typeof e.exitCode === "number") return e.exitCode as number;
  return 1;
}

async function main(): Promise<void> {
  await program.parseAsync(process.argv);
}

main().catch((err: unknown) => {
  const noColor =
    process.env.NO_COLOR !== undefined || process.argv.includes("--no-color");
  const msg = err instanceof Error ? err.message : String(err);
  process.stderr.write((noColor ? "error: " : pc.red("✖ ")) + msg + "\n");
  if (process.env.OPENAGENT_DEBUG && err instanceof Error && err.stack) {
    process.stderr.write(err.stack + "\n");
  }
  const code = exitCodeFor(err);
  // Validation errors without explicit code: commander uses exit 1; map invalid-argument to 2.
  if (code === 1 && /validation|invalid|unknown|required/i.test(msg)) {
    process.exitCode = /auth|401|403/i.test(msg) ? 3 : 1;
  } else {
    process.exitCode = code;
  }
});
