import { spawn, ChildProcessWithoutNullStreams } from "child_process";
import { AbstractTransport } from "./transport";
import {
  MCPTransportType,
  MCPServerConfig,
  MCPRequest,
  MCPResponse,
} from "./types";

export class StdioTransport extends AbstractTransport {
  readonly transportType: MCPTransportType = "stdio";
  private process?: ChildProcessWithoutNullStreams;
  private buffer = "";
  private readonly maxOutputSize = 10 * 1024 * 1024;

  protected async doConnect(): Promise<void> {
    if (!this.config.command) {
      throw new Error("STDIO transport requires a command");
    }

    const allowedCommands = this.getAllowedCommands();
    const commandPath = this.resolveCommand(
      this.config.command,
      allowedCommands,
    );

    if (!commandPath) {
      throw new Error(
        `Command not allowed or not found: ${this.config.command}`,
      );
    }

    const env = this.buildEnvironment();

    this.process = spawn(commandPath, this.config.args || [], {
      cwd: this.config.configuration?.working_directory || process.cwd(),
      env,
      stdio: ["pipe", "pipe", "pipe"],
    });

    this.process.stdout.on("data", (data: Buffer) => {
      this.handleData(data.toString());
    });

    this.process.stderr.on("data", (data: Buffer) => {
      this.handleError(data.toString());
    });

    this.process.on("error", (error: Error) => {
      this.emit("error", error);
    });

    this.process.on("exit", (code: number | null, signal: string | null) => {
      this.connected = false;
      this.setState(code === 0 ? "DISCONNECTED" : "ERROR");
      this.emit(
        "close",
        new Error(`Process exited with code ${code}, signal ${signal}`),
      );
    });

    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error("Connection timeout"));
      }, 10000);

      const checkConnection = () => {
        if (this.connected) {
          clearTimeout(timeout);
          resolve();
        } else if (
          this.getState() === "ERROR" ||
          this.getState() === "DISCONNECTED"
        ) {
          clearTimeout(timeout);
          reject(new Error("Process failed to start"));
        } else {
          setTimeout(checkConnection, 100);
        }
      };
      checkConnection();
    });
  }

  protected async doDisconnect(): Promise<void> {
    if (this.process && !this.process.killed) {
      this.process.kill("SIGTERM");

      await new Promise<void>((resolve) => {
        const timeout = setTimeout(() => {
          if (this.process && !this.process.killed) {
            this.process.kill("SIGKILL");
          }
          resolve();
        }, 5000);

        this.process!.once("exit", () => {
          clearTimeout(timeout);
          resolve();
        });
      });
    }
  }

  protected async doSend(request: MCPRequest): Promise<void> {
    if (!this.process || !this.process.stdin.writable) {
      throw new Error("Process stdin not writable");
    }

    const message = JSON.stringify(request) + "\n";
    this.process.stdin.write(message);
  }

  private handleData(data: string): void {
    this.buffer += data;

    let newlineIndex;
    while ((newlineIndex = this.buffer.indexOf("\n")) !== -1) {
      const line = this.buffer.slice(0, newlineIndex).trim();
      this.buffer = this.buffer.slice(newlineIndex + 1);

      if (line) {
        try {
          const response = JSON.parse(line);
          this.handleResponse(response);
        } catch (error) {
          this.emit("error", new Error(`Failed to parse response: ${error}`));
        }
      }
    }

    if (this.buffer.length > this.maxOutputSize) {
      this.buffer = this.buffer.slice(-this.maxOutputSize);
    }
  }

  private handleError(data: string): void {
    console.error(`[MCP STDERR] ${data}`);
  }

  private getAllowedCommands(): string[] {
    const configured = this.config.configuration?.allowed_commands as
      string[] | undefined;
    if (configured) return configured;

    return [
      "node",
      "python3",
      "python",
      "npx",
      "uvx",
      "docker",
      "mcp-server-github",
      "mcp-server-filesystem",
      "mcp-server-sqlite",
      "mcp-server-postgres",
      "mcp-server-brave-search",
    ];
  }

  private resolveCommand(
    command: string,
    allowedCommands: string[],
  ): string | null {
    if (allowedCommands.includes(command)) {
      return command;
    }

    if (command.includes("/") || command.includes("\\")) {
      return null;
    }

    const path = require("path");
    const which = require("which");

    try {
      const resolved = which.sync(command);
      const basename = path.basename(resolved);
      if (allowedCommands.includes(basename)) {
        return resolved;
      }
    } catch {
      return null;
    }

    return null;
  }

  private buildEnvironment(): NodeJS.ProcessEnv {
    const allowedEnv = this.config.configuration?.allowed_env as
      string[] | undefined;
    const baseEnv: Record<string, string> = {
      PATH: process.env.PATH || "",
      LANG: "en_US.UTF-8",
      LC_ALL: "en_US.UTF-8",
    };

    if (allowedEnv) {
      for (const key of allowedEnv) {
        if (process.env[key]) {
          baseEnv[key] = process.env[key]!;
        }
      }
    }

    if (this.config.env) {
      Object.assign(baseEnv, this.config.env);
    }

    return baseEnv;
  }
}
