import {
  ToolDefinition,
  ToolExecutionContext,
  ToolResult,
  ToolAdapter,
} from "./types";
import { OpenAgentLogger, createChildLogger } from "@openagent/logger";
import type { BinaryToTextEncoding } from "crypto";

const logger: OpenAgentLogger = createChildLogger({
  module: "tool-system:builtins",
});

export const BUILTIN_TOOLS: ToolDefinition[] = [
  {
    id: "builtin-http-request",
    slug: "http.request",
    metadata: {
      name: "http.request",
      display_name: "HTTP Request",
      description: "Make HTTP requests to external APIs",
      icon: "globe",
      category: "http",
      tags: ["http", "api", "web", "request"],
      documentation_url: "https://docs.openagent.ai/tools/http-request",
      provider: "builtin",
      version: "1.0.0",
      capabilities: ["network", "external_api", "read"],
      risk_level: "MEDIUM",
      execution_mode: "SYNC",
      timeout: 30000,
      retry_policy: {
        max_attempts: 3,
        backoff: 1000,
        jitter: 500,
        retryable_errors: [
          "TOOL_TIMEOUT",
          "TOOL_UNAVAILABLE",
          "PROVIDER_ERROR",
        ],
      },
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: false,
      trust_level: "CORE",
    },
    input_schema: {
      type: "object",
      properties: {
        url: {
          type: "string",
          format: "uri",
          description: "The URL to request",
        },
        method: {
          type: "string",
          enum: ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
          default: "GET",
        },
        headers: {
          type: "object",
          additionalProperties: { type: "string" },
          description: "HTTP headers",
        },
        query: {
          type: "object",
          additionalProperties: { type: "string" },
          description: "Query parameters",
        },
        body: {
          type: ["string", "object", "null"],
          description: "Request body",
        },
        timeout: {
          type: "number",
          default: 30000,
          description: "Request timeout in milliseconds",
        },
        follow_redirects: { type: "boolean", default: true },
        max_redirects: { type: "number", default: 10 },
        validate_certificates: { type: "boolean", default: true },
      },
      required: ["url"],
    },
    output_schema: {
      type: "object",
      properties: {
        status: { type: "number", description: "HTTP status code" },
        status_text: { type: "string", description: "HTTP status text" },
        headers: { type: "object", additionalProperties: { type: "string" } },
        body: { type: ["string", "object"] },
        url: { type: "string", description: "Final URL after redirects" },
        duration_ms: {
          type: "number",
          description: "Request duration in milliseconds",
        },
      },
      required: [
        "status",
        "status_text",
        "headers",
        "body",
        "url",
        "duration_ms",
      ],
    },
    status: "ACTIVE",
    configuration: {
      allowed_schemes: ["http", "https"],
      blocked_domains: ["localhost", "127.0.0.1", "0.0.0.0"],
      blocked_ips: [
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "127.0.0.0/8",
      ],
      max_response_size: 10 * 1024 * 1024,
      max_redirects: 10,
    },
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: "builtin-json-transform",
    slug: "json.transform",
    metadata: {
      name: "json.transform",
      display_name: "JSON Transform",
      description: "Transform JSON data using jq-like expressions",
      icon: "code",
      category: "utility",
      tags: ["json", "transform", "data", "manipulation"],
      documentation_url: "https://docs.openagent.ai/tools/json-transform",
      provider: "builtin",
      version: "1.0.0",
      capabilities: ["read"],
      risk_level: "LOW",
      execution_mode: "SYNC",
      timeout: 5000,
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: true,
      trust_level: "CORE",
    },
    input_schema: {
      type: "object",
      properties: {
        input: { type: "object", description: "Input JSON data" },
        expression: {
          type: "string",
          description: "Transform expression (jq-like syntax)",
        },
      },
      required: ["input", "expression"],
    },
    output_schema: {
      type: "object",
      properties: {
        result: { description: "Transformed result" },
      },
    },
    status: "ACTIVE",
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: "builtin-text-transform",
    slug: "text.transform",
    metadata: {
      name: "text.transform",
      display_name: "Text Transform",
      description: "Transform text using various operations",
      icon: "type",
      category: "utility",
      tags: ["text", "transform", "string", "manipulation"],
      documentation_url: "https://docs.openagent.ai/tools/text-transform",
      provider: "builtin",
      version: "1.0.0",
      capabilities: ["read"],
      risk_level: "LOW",
      execution_mode: "SYNC",
      timeout: 5000,
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: true,
      trust_level: "CORE",
    },
    input_schema: {
      type: "object",
      properties: {
        input: { type: "string", description: "Input text" },
        operation: {
          type: "string",
          enum: [
            "uppercase",
            "lowercase",
            "trim",
            "reverse",
            "base64_encode",
            "base64_decode",
            "url_encode",
            "url_decode",
            "hash_sha256",
            "hash_md5",
          ],
          description: "Transform operation",
        },
        options: { type: "object", description: "Operation-specific options" },
      },
      required: ["input", "operation"],
    },
    output_schema: {
      type: "object",
      properties: {
        result: { type: "string", description: "Transformed text" },
      },
    },
    status: "ACTIVE",
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: "builtin-datetime",
    slug: "utility.datetime",
    metadata: {
      name: "utility.datetime",
      display_name: "Date/Time Utility",
      description: "Perform date/time operations and formatting",
      icon: "clock",
      category: "utility",
      tags: ["date", "time", "datetime", "format", "parse"],
      documentation_url: "https://docs.openagent.ai/tools/datetime",
      provider: "builtin",
      version: "1.0.0",
      capabilities: ["read"],
      risk_level: "LOW",
      execution_mode: "SYNC",
      timeout: 5000,
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: true,
      trust_level: "CORE",
    },
    input_schema: {
      type: "object",
      properties: {
        operation: {
          type: "string",
          enum: [
            "now",
            "format",
            "parse",
            "add",
            "subtract",
            "diff",
            "timezone",
            "unix",
          ],
          description: "Operation to perform",
        },
        input: {
          type: ["string", "number", "null"],
          description: "Input date/time",
        },
        format: {
          type: "string",
          description: "Format string (for format/parse operations)",
        },
        timezone: {
          type: "string",
          description: "Timezone (e.g., UTC, America/New_York)",
        },
        amount: { type: "number", description: "Amount for add/subtract" },
        unit: {
          type: "string",
          enum: [
            "milliseconds",
            "seconds",
            "minutes",
            "hours",
            "days",
            "weeks",
            "months",
            "years",
          ],
        },
      },
      required: ["operation"],
    },
    output_schema: {
      type: "object",
      properties: {
        result: { type: ["string", "number"], description: "Operation result" },
        iso: { type: "string", description: "ISO 8601 formatted date" },
        unix: { type: "number", description: "Unix timestamp in milliseconds" },
      },
    },
    status: "ACTIVE",
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: "builtin-calculator",
    slug: "utility.calculator",
    metadata: {
      name: "utility.calculator",
      display_name: "Calculator",
      description: "Perform mathematical calculations",
      icon: "calculator",
      category: "utility",
      tags: ["math", "calculate", "arithmetic", "expression"],
      documentation_url: "https://docs.openagent.ai/tools/calculator",
      provider: "builtin",
      version: "1.0.0",
      capabilities: ["read"],
      risk_level: "LOW",
      execution_mode: "SYNC",
      timeout: 5000,
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: true,
      trust_level: "CORE",
    },
    input_schema: {
      type: "object",
      properties: {
        expression: {
          type: "string",
          description: "Mathematical expression to evaluate",
        },
        precision: {
          type: "number",
          default: 10,
          description: "Decimal precision",
        },
      },
      required: ["expression"],
    },
    output_schema: {
      type: "object",
      properties: {
        result: { type: "number", description: "Calculation result" },
        expression: { type: "string", description: "Original expression" },
      },
    },
    status: "ACTIVE",
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: "builtin-uuid",
    slug: "utility.uuid",
    metadata: {
      name: "utility.uuid",
      display_name: "UUID Generator",
      description: "Generate UUIDs (v4 random, v7 timestamp-based)",
      icon: "fingerprint",
      category: "utility",
      tags: ["uuid", "generate", "id", "unique"],
      documentation_url: "https://docs.openagent.ai/tools/uuid",
      provider: "builtin",
      version: "1.0.0",
      capabilities: ["read"],
      risk_level: "LOW",
      execution_mode: "SYNC",
      timeout: 1000,
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: false,
      trust_level: "CORE",
    },
    input_schema: {
      type: "object",
      properties: {
        version: {
          type: "string",
          enum: ["v4", "v7"],
          default: "v4",
          description: "UUID version to generate",
        },
        count: {
          type: "number",
          default: 1,
          minimum: 1,
          maximum: 100,
          description: "Number of UUIDs to generate",
        },
      },
    },
    output_schema: {
      type: "object",
      properties: {
        uuids: {
          type: "array",
          items: { type: "string" },
          description: "Generated UUIDs",
        },
      },
    },
    status: "ACTIVE",
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: "builtin-hash",
    slug: "utility.hash",
    metadata: {
      name: "utility.hash",
      display_name: "Hash Generator",
      description: "Generate cryptographic hashes",
      icon: "hash",
      category: "utility",
      tags: ["hash", "crypto", "sha256", "md5", "sha512"],
      documentation_url: "https://docs.openagent.ai/tools/hash",
      provider: "builtin",
      version: "1.0.0",
      capabilities: ["read"],
      risk_level: "LOW",
      execution_mode: "SYNC",
      timeout: 5000,
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: true,
      trust_level: "CORE",
    },
    input_schema: {
      type: "object",
      properties: {
        input: { type: "string", description: "Input string to hash" },
        algorithm: {
          type: "string",
          enum: ["md5", "sha1", "sha256", "sha512"],
          default: "sha256",
          description: "Hash algorithm",
        },
        encoding: {
          type: "string",
          enum: ["hex", "base64"],
          default: "hex",
          description: "Output encoding",
        },
      },
      required: ["input"],
    },
    output_schema: {
      type: "object",
      properties: {
        hash: { type: "string", description: "Generated hash" },
        algorithm: { type: "string", description: "Algorithm used" },
      },
    },
    status: "ACTIVE",
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: "builtin-base64",
    slug: "utility.base64",
    metadata: {
      name: "utility.base64",
      display_name: "Base64 Encoder/Decoder",
      description: "Encode or decode Base64 strings",
      icon: "file-text",
      category: "utility",
      tags: ["base64", "encode", "decode", "string"],
      documentation_url: "https://docs.openagent.ai/tools/base64",
      provider: "builtin",
      version: "1.0.0",
      capabilities: ["read"],
      risk_level: "LOW",
      execution_mode: "SYNC",
      timeout: 5000,
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: true,
      trust_level: "CORE",
    },
    input_schema: {
      type: "object",
      properties: {
        input: { type: "string", description: "Input string" },
        operation: {
          type: "string",
          enum: ["encode", "decode"],
          description: "Operation to perform",
        },
      },
      required: ["input", "operation"],
    },
    output_schema: {
      type: "object",
      properties: {
        result: { type: "string", description: "Encoded/decoded result" },
      },
    },
    status: "ACTIVE",
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
];

export class BuiltinToolAdapter implements ToolAdapter {
  readonly adapter_id = "builtin";
  readonly supported_tool_types = ["builtin"];

  async validate(
    tool: ToolDefinition,
    input: Record<string, unknown>,
  ): Promise<{
    valid: boolean;
    errors: { field: string; message: string; code: string }[];
  }> {
    const errors: { field: string; message: string; code: string }[] = [];

    const required = tool.input_schema.required || [];
    for (const field of required) {
      if (!(field in input)) {
        errors.push({
          field,
          message: `Required field '${field}' is missing`,
          code: "REQUIRED_FIELD_MISSING",
        });
      }
    }

    return { valid: errors.length === 0, errors };
  }

  async execute(
    context: ToolExecutionContext,
    input: Record<string, unknown>,
  ): Promise<ToolResult> {
    const startTime = Date.now();

    try {
      let output: Record<string, unknown>;

      switch (context.metadata.tool_name) {
        case "http.request":
          output = await this.executeHttpRequest(input, context);
          break;
        case "json.transform":
          output = await this.executeJsonTransform(input);
          break;
        case "text.transform":
          output = await this.executeTextTransform(input);
          break;
        case "utility.datetime":
          output = await this.executeDateTime(input);
          break;
        case "utility.calculator":
          output = await this.executeCalculator(input);
          break;
        case "utility.uuid":
          output = await this.executeUuid(input);
          break;
        case "utility.hash":
          output = await this.executeHash(input);
          break;
        case "utility.base64":
          output = await this.executeBase64(input);
          break;
        default:
          throw new Error(
            `Unknown builtin tool: ${context.metadata.tool_name}`,
          );
      }

      return {
        success: true,
        output,
        metadata: { adapter: "builtin" },
        duration_ms: Date.now() - startTime,
        retryable: false,
        truncated: false,
        artifacts: [],
      };
    } catch (error) {
      return {
        success: false,
        error: {
          code: "TOOL_EXECUTION_FAILED",
          message: String(error),
          retryable: false,
        },
        metadata: { adapter: "builtin" },
        duration_ms: Date.now() - startTime,
        retryable: false,
        truncated: false,
        artifacts: [],
      };
    }
  }

  async cancel(executionId: string): Promise<void> {
    logger.info("Builtin tool cancellation requested", {
      execution_id: executionId,
    });
  }

  private async executeHttpRequest(
    input: Record<string, unknown>,
    context: ToolExecutionContext,
  ): Promise<Record<string, unknown>> {
    const toolConfig =
      (context.metadata.tool_config as Record<string, unknown>) || {};

    const url = input.url as string;
    const method = (input.method as string) || "GET";
    const headers = (input.headers as Record<string, string>) || {};
    const query = input.query as Record<string, string> | undefined;
    const body = input.body;
    const timeout = (input.timeout as number) || 30000;
    const followRedirects = input.follow_redirects !== false;
    // const maxRedirects = (input.max_redirects as number) || 10; // TODO: implement redirect limit
    // const validateCertificates = input.validate_certificates !== false; // TODO: implement cert validation

    const allowedSchemes = (toolConfig.allowed_schemes as string[]) || [
      "http",
      "https",
    ];
    const blockedDomains = (toolConfig.blocked_domains as string[]) || [
      "localhost",
      "127.0.0.1",
      "0.0.0.0",
    ];
    // const blockedIps = (toolConfig.blocked_ips as string[]) || ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16', '127.0.0.0/8']; // TODO: implement IP blocking
    const maxResponseSize =
      (toolConfig.max_response_size as number) || 10 * 1024 * 1024;

    const parsedUrl = new URL(url);
    if (!allowedSchemes.includes(parsedUrl.protocol.replace(":", ""))) {
      throw new Error(`Scheme ${parsedUrl.protocol} not allowed`);
    }

    const hostname = parsedUrl.hostname;
    if (
      blockedDomains.some((d) => hostname === d || hostname.endsWith("." + d))
    ) {
      throw new Error(`Domain ${hostname} is blocked`);
    }

    const fullUrl = query
      ? `${url}?${new URLSearchParams(query).toString()}`
      : url;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
      const fetchOptions: RequestInit = {
        method,
        headers: {
          "User-Agent": "OpenAgent/1.0",
          ...headers,
        },
        signal: controller.signal,
        redirect: followRedirects ? "follow" : "manual",
      };

      if (body !== undefined && method !== "GET" && method !== "HEAD") {
        if (typeof body === "object") {
          fetchOptions.headers = {
            ...fetchOptions.headers,
            "Content-Type": "application/json",
          };
          fetchOptions.body = JSON.stringify(body);
        } else {
          fetchOptions.body = body as string;
        }
      }

      const response = await fetch(fullUrl, fetchOptions);
      clearTimeout(timeoutId);

      const responseHeaders: Record<string, string> = {};
      response.headers.forEach((value, key) => {
        responseHeaders[key] = value;
      });

      let responseBody: string | object;
      const contentType = response.headers.get("content-type") || "";

      if (contentType.includes("application/json")) {
        responseBody = (await response.json()) as string | object;
      } else {
        const text = await response.text();
        if (text.length > maxResponseSize) {
          responseBody = text.substring(0, maxResponseSize) + "... [truncated]";
        } else {
          responseBody = text;
        }
      }

      return {
        status: response.status,
        status_text: response.statusText,
        headers: responseHeaders,
        body: responseBody,
        url: response.url,
        duration_ms:
          Date.now() -
          ((context.metadata.request_start as number) || Date.now()),
      };
    } catch (error) {
      clearTimeout(timeoutId);
      if (error instanceof Error && error.name === "AbortError") {
        throw new Error("Request timeout");
      }
      throw error;
    }
  }

  private async executeJsonTransform(
    input: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const data = input.input as Record<string, unknown>;
    const expression = input.expression as string;

    const result = this.evaluateJsonPath(data, expression);

    return { result };
  }

  private evaluateJsonPath(obj: unknown, path: string): unknown {
    if (path === "." || path === "") return obj;

    const parts = path.split(".").filter((p) => p);
    let current: unknown = obj;

    for (const part of parts) {
      if (current === null || current === undefined) return undefined;

      if (part.startsWith("[") && part.endsWith("]")) {
        const index = parseInt(part.slice(1, -1), 10);
        if (Array.isArray(current)) {
          current = current[index];
        } else {
          return undefined;
        }
      } else if (part === "[]") {
        if (Array.isArray(current)) {
          return current;
        }
        return undefined;
      } else {
        if (typeof current === "object" && current !== null) {
          current = (current as Record<string, unknown>)[part];
        } else {
          return undefined;
        }
      }
    }

    return current;
  }

  private async executeTextTransform(
    input: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const text = input.input as string;
    const operation = input.operation as string;
    // const options = input.options as Record<string, unknown> || {}; // Reserved for future use

    let result: string;

    switch (operation) {
      case "uppercase":
        result = text.toUpperCase();
        break;
      case "lowercase":
        result = text.toLowerCase();
        break;
      case "trim":
        result = text.trim();
        break;
      case "reverse":
        result = text.split("").reverse().join("");
        break;
      case "base64_encode":
        result = Buffer.from(text, "utf8").toString("base64");
        break;
      case "base64_decode":
        result = Buffer.from(text, "base64").toString("utf8");
        break;
      case "url_encode":
        result = encodeURIComponent(text);
        break;
      case "url_decode":
        result = decodeURIComponent(text);
        break;
      case "hash_sha256": {
        const crypto = await import("crypto");
        result = crypto.createHash("sha256").update(text).digest("hex");
        break;
      }
      case "hash_md5": {
        const crypto = await import("crypto");
        result = crypto.createHash("md5").update(text).digest("hex");
        break;
      }
      default:
        throw new Error(`Unknown text operation: ${operation}`);
    }

    return { result };
  }

  private async executeDateTime(
    input: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const operation = input.operation as string;
    const inputValue = input.input;
    const format = input.format as string | undefined;
    const timezone = input.timezone as string | undefined;
    const amount = input.amount as number | undefined;
    const unit = input.unit as string | undefined;

    let date: Date;

    if (operation === "now") {
      date = new Date();
    } else if (inputValue !== undefined) {
      if (typeof inputValue === "number") {
        date = new Date(inputValue);
      } else {
        date = new Date(inputValue as string);
      }
    } else {
      date = new Date();
    }

    if (isNaN(date.getTime())) {
      throw new Error("Invalid date");
    }

    let result: string | number;

    switch (operation) {
      case "now":
      case "format":
        result = format
          ? this.formatDate(date, format, timezone)
          : date.toISOString();
        break;
      case "parse":
        result = date.getTime();
        break;
      case "add":
        if (amount !== undefined && unit) {
          date = this.addTime(date, amount, unit);
        }
        result = date.toISOString();
        break;
      case "subtract":
        if (amount !== undefined && unit) {
          date = this.addTime(date, -amount, unit);
        }
        result = date.toISOString();
        break;
      case "diff":
        if (amount !== undefined && unit) {
          const otherDate = new Date(amount);
          result = this.diffDates(date, otherDate, unit);
        } else {
          throw new Error("diff operation requires amount and unit");
        }
        break;
      case "timezone":
        result = this.formatDate(
          date,
          format || "YYYY-MM-DD HH:mm:ss",
          timezone,
        );
        break;
      case "unix":
        result = date.getTime();
        break;
      default:
        throw new Error(`Unknown datetime operation: ${operation}`);
    }

    return {
      result,
      iso: date.toISOString(),
      unix: date.getTime(),
    };
  }

  private formatDate(date: Date, format: string, _timezone?: string): string {
    // const opts: Intl.DateTimeFormatOptions = { timeZone: timezone || 'UTC' };
    // const fmt = new Intl.DateTimeFormat('en-US', opts); // Reserved for future use

    const replacements: Record<string, string> = {
      YYYY: date.getFullYear().toString(),
      YY: date.getFullYear().toString().slice(-2),
      MM: (date.getMonth() + 1).toString().padStart(2, "0"),
      M: (date.getMonth() + 1).toString(),
      DD: date.getDate().toString().padStart(2, "0"),
      D: date.getDate().toString(),
      HH: date.getHours().toString().padStart(2, "0"),
      H: date.getHours().toString(),
      mm: date.getMinutes().toString().padStart(2, "0"),
      m: date.getMinutes().toString(),
      ss: date.getSeconds().toString().padStart(2, "0"),
      s: date.getSeconds().toString(),
    };

    let result = format;
    for (const [key, value] of Object.entries(replacements)) {
      result = result.replace(new RegExp(key, "g"), value);
    }
    return result;
  }

  private addTime(date: Date, amount: number, unit: string): Date {
    const newDate = new Date(date);
    switch (unit) {
      case "milliseconds":
        newDate.setMilliseconds(newDate.getMilliseconds() + amount);
        break;
      case "seconds":
        newDate.setSeconds(newDate.getSeconds() + amount);
        break;
      case "minutes":
        newDate.setMinutes(newDate.getMinutes() + amount);
        break;
      case "hours":
        newDate.setHours(newDate.getHours() + amount);
        break;
      case "days":
        newDate.setDate(newDate.getDate() + amount);
        break;
      case "weeks":
        newDate.setDate(newDate.getDate() + amount * 7);
        break;
      case "months":
        newDate.setMonth(newDate.getMonth() + amount);
        break;
      case "years":
        newDate.setFullYear(newDate.getFullYear() + amount);
        break;
    }
    return newDate;
  }

  private diffDates(date1: Date, date2: Date, unit: string): number {
    const diffMs = Math.abs(date1.getTime() - date2.getTime());
    switch (unit) {
      case "milliseconds":
        return diffMs;
      case "seconds":
        return Math.floor(diffMs / 1000);
      case "minutes":
        return Math.floor(diffMs / 60000);
      case "hours":
        return Math.floor(diffMs / 3600000);
      case "days":
        return Math.floor(diffMs / 86400000);
      case "weeks":
        return Math.floor(diffMs / 604800000);
      case "months":
        return Math.floor(diffMs / 2629746000);
      case "years":
        return Math.floor(diffMs / 31556952000);
      default:
        return diffMs;
    }
  }

  private async executeCalculator(
    input: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const expression = input.expression as string;
    const precision = (input.precision as number) || 10;

    const sanitized = expression.replace(/[^0-9+\-*/().%\s]/g, "");
    if (sanitized !== expression.replace(/\s/g, "")) {
      throw new Error("Invalid characters in expression");
    }

    try {
      const result = Function('"use strict"; return (' + sanitized + ")")();
      if (typeof result !== "number" || !isFinite(result)) {
        throw new Error("Invalid result");
      }
      return {
        result: Number(result.toFixed(precision)),
        expression,
      };
    } catch {
      throw new Error("Invalid expression");
    }
  }

  private async executeUuid(
    input: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const version = (input.version as string) || "v4";
    const count = (input.count as number) || 1;

    const uuids: string[] = [];
    for (let i = 0; i < count; i++) {
      if (version === "v7") {
        uuids.push(this.generateUuidV7());
      } else {
        uuids.push(this.generateUuidV4());
      }
    }

    return { uuids };
  }

  private generateUuidV4(): string {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  private generateUuidV7(): string {
    const now = Date.now();
    const timeHex = now.toString(16).padStart(12, "0");
    const randomPart = Array.from({ length: 20 }, () =>
      Math.floor(Math.random() * 16).toString(16),
    ).join("");
    return `${timeHex.slice(0, 8)}-${timeHex.slice(8, 12)}-7${timeHex.slice(12, 15)}-${randomPart.slice(0, 3)}${randomPart.slice(3, 4)}${randomPart.slice(4, 16)}`;
  }

  private async executeHash(
    input: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const text = input.input as string;
    const algorithm = (input.algorithm as string) || "sha256";
    const encoding = ((input.encoding as string) || "hex") as BufferEncoding;

    // Valid BinaryToTextEncoding values
    const validEncodings: BinaryToTextEncoding[] = [
      "hex",
      "base64",
      "base64url",
    ];
    const safeEncoding = validEncodings.includes(
      encoding as BinaryToTextEncoding,
    )
      ? (encoding as BinaryToTextEncoding)
      : "hex";

    const crypto = await import("crypto");
    const hash = crypto.createHash(algorithm).update(text).digest(safeEncoding);

    return { hash, algorithm };
  }

  private async executeBase64(
    input: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const text = input.input as string;
    const operation = input.operation as string;

    let result: string;
    if (operation === "encode") {
      result = Buffer.from(text, "utf8").toString("base64");
    } else {
      result = Buffer.from(text, "base64").toString("utf8");
    }

    return { result };
  }
}

export function createBuiltinAdapter(): BuiltinToolAdapter {
  return new BuiltinToolAdapter();
}
