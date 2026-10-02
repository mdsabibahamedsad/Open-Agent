import { ToolResult, ToolError } from "./types";
import { OpenAgentLogger, createChildLogger } from "@openagent/logger";

const logger: OpenAgentLogger = createChildLogger({
  module: "tool-system:secrets",
});

export interface RedactionPattern {
  pattern: RegExp;
  replacement: string;
  description: string;
}

export class SecretRedactor {
  private patterns: RedactionPattern[] = [
    {
      pattern:
        /(?:api[_-]?key|apikey|secret|token|password|passwd|private[_-]?key|client[_-]?secret|access[_-]?key|auth[_-]?token|secret[_-]?key|api[_-]?secret)["']?\s*[:=]\s*["']?([a-zA-Z0-9_\-]{16,})["']?/gi,
      replacement: "***REDACTED***",
      description: "API keys and secrets",
    },
    {
      pattern: /(?:Bearer\s+)([a-zA-Z0-9_\-\.]{20,})/gi,
      replacement: "Bearer ***REDACTED***",
      description: "Bearer tokens",
    },
    {
      pattern: /(?:Basic\s+)([a-zA-Z0-9+/=]{20,})/gi,
      replacement: "Basic ***REDACTED***",
      description: "Basic auth tokens",
    },
    {
      pattern: /sk-[a-zA-Z0-9]{32,}/g,
      replacement: "sk-***REDACTED***",
      description: "OpenAI-style API keys",
    },
    {
      pattern: /gh[pousr]_[a-zA-Z0-9]{36,}/g,
      replacement: "gh***REDACTED***",
      description: "GitHub tokens",
    },
    {
      pattern: /xoxb-[0-9]{10,}-[0-9]{10,}-[a-zA-Z0-9]{24,}/g,
      replacement: "xoxb-***REDACTED***",
      description: "Slack bot tokens",
    },
    {
      pattern: /AWS[A-Z0-9]{16,}/g,
      replacement: "AWS***REDACTED***",
      description: "AWS access keys",
    },
    {
      pattern: /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi,
      replacement: "***UUID_REDACTED***",
      description: "UUIDs (potential secrets)",
    },
    {
      pattern: /mongodb(?:\+srv)?:\/\/[^:]+:[^@]+@/gi,
      replacement: "mongodb://***REDACTED***@",
      description: "MongoDB connection strings",
    },
    {
      pattern: /postgres(?:ql)?:\/\/[^:]+:[^@]+@/gi,
      replacement: "postgresql://***REDACTED***@",
      description: "PostgreSQL connection strings",
    },
    {
      pattern: /mysql:\/\/[^:]+:[^@]+@/gi,
      replacement: "mysql://***REDACTED***@",
      description: "MySQL connection strings",
    },
    {
      pattern: /redis:\/\/[^:]+:[^@]+@/gi,
      replacement: "redis://***REDACTED***@",
      description: "Redis connection strings",
    },
  ];

  private customPatterns: RedactionPattern[] = [];

  addPattern(pattern: RedactionPattern): void {
    this.customPatterns.push(pattern);
  }

  removePattern(description: string): boolean {
    const index = this.customPatterns.findIndex(
      (p) => p.description === description,
    );
    if (index >= 0) {
      this.customPatterns.splice(index, 1);
      return true;
    }
    return false;
  }

  redact(text: string): string {
    let result = text;
    const allPatterns = [...this.patterns, ...this.customPatterns];

    for (const { pattern, replacement } of allPatterns) {
      result = result.replace(pattern, replacement);
    }

    return result;
  }

  redactObject(obj: unknown): unknown {
    if (typeof obj === "string") {
      return this.redact(obj);
    }

    if (Array.isArray(obj)) {
      return obj.map((item) => this.redactObject(item));
    }

    if (obj !== null && typeof obj === "object") {
      const result: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(obj)) {
        if (this.isSecretKey(key)) {
          result[key] = "***REDACTED***";
        } else {
          result[key] = this.redactObject(value);
        }
      }
      return result;
    }

    return obj;
  }

  redactResult(result: ToolResult): ToolResult {
    return {
      ...result,
      output: result.output
        ? (this.redactObject(result.output) as Record<string, unknown>)
        : undefined,
      error: result.error ? this.redactError(result.error) : undefined,
      metadata: this.redactObject(result.metadata) as Record<string, unknown>,
    };
  }

  redactError(error: ToolError): ToolError {
    return {
      ...error,
      message: this.redact(error.message),
      details: error.details
        ? (this.redactObject(error.details) as Record<string, unknown>)
        : undefined,
    };
  }

  redactExecutionRecord(
    record: Record<string, unknown>,
  ): Record<string, unknown> {
    return this.redactObject(record) as Record<string, unknown>;
  }

  private isSecretKey(key: string): boolean {
    const lowerKey = key.toLowerCase();
    const secretKeys = [
      "api_key",
      "apikey",
      "secret",
      "token",
      "password",
      "passwd",
      "private_key",
      "client_secret",
      "access_key",
      "auth_token",
      "secret_key",
      "api_secret",
      "authorization",
      "cookie",
      "x-api-key",
      "x-auth-token",
    ];
    return secretKeys.some((sk) => lowerKey.includes(sk));
  }

  getPatterns(): RedactionPattern[] {
    return [...this.patterns, ...this.customPatterns];
  }
}

export function createSecretRedactor(): SecretRedactor {
  return new SecretRedactor();
}
