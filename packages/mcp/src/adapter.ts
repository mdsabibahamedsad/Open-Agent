import {
  ToolDefinition,
  ToolExecutionContext,
  ToolResult,
  ToolAdapter,
  JSONSchema,
  ToolErrorCode,
} from "@openagent/tool-system";

export interface MCPToolAdapterConfig {
  serverId: string;
  serverName: string;
}

export class MCPToolAdapter implements ToolAdapter {
  readonly adapter_id = "mcp";
  readonly supported_tool_types = ["mcp"];
  private serverId: string;

  constructor(config: { serverId: string; serverName: string }) {
    this.serverId = config.serverId;
  }

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

    const properties = tool.input_schema.properties || {};
    for (const [field, value] of Object.entries(input)) {
      const propSchema = properties[field] as JSONSchema;
      if (propSchema) {
        const typeError = this.validateType(field, value, propSchema);
        if (typeError) errors.push(typeError);
      }
    }

    return { valid: errors.length === 0, errors };
  }

  private validateType(
    field: string,
    value: unknown,
    schema: JSONSchema,
  ): { field: string; message: string; code: string } | null {
    const expectedType = schema.type;
    if (!expectedType) return null;

    const types = Array.isArray(expectedType) ? expectedType : [expectedType];
    for (const type of types) {
      if (type === "string" && typeof value === "string") return null;
      if (
        (type === "number" || type === "integer") &&
        typeof value === "number" &&
        !isNaN(value)
      )
        return null;
      if (type === "boolean" && typeof value === "boolean") return null;
      if (type === "array" && Array.isArray(value)) return null;
      if (
        type === "object" &&
        typeof value === "object" &&
        value !== null &&
        !Array.isArray(value)
      )
        return null;
    }

    return {
      field,
      message: `Field '${field}' must be of type ${expectedType}`,
      code: "TYPE_MISMATCH",
    };
  }

  async execute(
    _context: ToolExecutionContext,
    _input: Record<string, unknown>,
  ): Promise<ToolResult> {
    // In a real implementation, this would call the actual MCP client
    // For now, return a placeholder result
    return {
      success: false,
      error: {
        code: "TOOL_EXECUTION_FAILED" as ToolErrorCode,
        message: "MCP tool execution not yet implemented",
        retryable: false,
      },
      metadata: { adapter: "mcp", server_id: this.serverId },
      duration_ms: 0,
      retryable: false,
      truncated: false,
      artifacts: [],
    };
  }

  async cancel(executionId: string): Promise<void> {
    console.log("MCP tool cancellation requested", {
      execution_id: executionId,
      server_id: this.serverId,
    });
  }

  async healthCheck(_toolId: string): Promise<{
    status: "HEALTHY" | "DEGRADED" | "UNAVAILABLE";
    latency_ms: number;
  }> {
    const startTime = Date.now();
    return { status: "UNAVAILABLE", latency_ms: Date.now() - startTime };
  }
}

export async function createMCPToolAdapter(
  serverId: string,
  serverName: string,
  _mcpClient: any,
): Promise<any> {
  return {
    adapter_id: "mcp",
    supported_tool_types: ["mcp"],
    serverId,
    serverName,
    async validate(tool: any, input: any) {
      const errors: { field: string; message: string; code: string }[] = [];

      const required = tool.input_schema?.required || [];
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
    },
    async execute(_context: any, _input: any): Promise<any> {
      return {
        success: false,
        error: {
          code: "NOT_IMPLEMENTED",
          message: "MCP tool execution not yet implemented",
          retryable: false,
        },
        metadata: { adapter: "mcp", server_id: serverId },
        duration_ms: 0,
        retryable: false,
        truncated: false,
        artifacts: [],
      };
    },
    async cancel(executionId: string) {
      console.log("MCP tool cancellation requested", {
        execution_id: executionId,
        server_id: serverId,
      });
    },
    async healthCheck(_toolId: string) {
      const startTime = Date.now();
      return { status: "UNAVAILABLE", latency_ms: Date.now() - startTime };
    },
  };
}

export function createMCPToolDefinition(
  serverId: string,
  serverName: string,
  mcpTool: any,
): any {
  const capabilities = inferCapabilities(mcpTool);
  const riskLevel = inferRiskLevel(mcpTool, capabilities);

  return {
    id: `mcp-${serverId}-${mcpTool.name}`,
    slug: `mcp.${serverName}.${mcpTool.name}`,
    metadata: {
      name: `mcp.${serverName}.${mcpTool.name}`,
      display_name: mcpTool.title || mcpTool.name,
      description: mcpTool.description || "",
      icon: "server",
      category: "custom",
      tags: ["mcp", serverId, serverName],
      documentation_url: undefined,
      provider: `mcp-${serverId}`,
      version: "1.0.0",
      capabilities,
      risk_level: riskLevel,
      execution_mode: "SYNC",
      timeout: 60000,
      retry_policy: {
        max_attempts: 2,
        backoff: 1000,
        jitter: 500,
        retryable_errors: ["MCP_TIMEOUT", "MCP_SERVER_UNAVAILABLE"],
      },
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: false,
      trust_level: "COMMUNITY",
    },
    input_schema: normalizeMCPToolSchema(mcpTool.inputSchema),
    output_schema: mcpTool.outputSchema
      ? normalizeMCPToolSchema(mcpTool.outputSchema)
      : undefined,
    status: "ACTIVE",
    configuration: { mcp_server: serverId, mcp_tool: mcpTool.name },
    created_at: new Date(),
    updated_at: new Date(),
  };
}

function inferCapabilities(tool: any): string[] {
  const caps = ["read"];

  const annotations = tool.annotations;
  if (annotations) {
    if (annotations.destructiveHint) caps.push("delete");
    if (!annotations.readOnlyHint && !annotations.destructiveHint)
      caps.push("write");
    if (annotations.openWorldHint) caps.push("network");
  }

  const name = tool.name.toLowerCase();
  if (
    name.includes("search") ||
    name.includes("query") ||
    name.includes("list") ||
    name.includes("get")
  ) {
    caps.push("read");
  }
  if (
    name.includes("create") ||
    name.includes("write") ||
    name.includes("put") ||
    name.includes("post")
  ) {
    caps.push("write");
  }
  if (
    name.includes("delete") ||
    name.includes("remove") ||
    name.includes("destroy")
  ) {
    caps.push("delete");
  }
  if (
    name.includes("exec") ||
    name.includes("run") ||
    name.includes("invoke")
  ) {
    caps.push("process_execution");
  }

  return [...new Set(caps)];
}

function inferRiskLevel(tool: any, capabilities: string[]): string {
  const annotations = tool.annotations;

  if (annotations?.destructiveHint) return "HIGH";
  if (capabilities.includes("process_execution")) return "CRITICAL";
  if (
    capabilities.includes("delete") ||
    capabilities.includes("financial_action")
  )
    return "HIGH";
  if (
    capabilities.includes("write") ||
    capabilities.includes("network") ||
    capabilities.includes("external_api")
  )
    return "MEDIUM";
  if (
    capabilities.includes("credential_access") ||
    capabilities.includes("database_access")
  )
    return "HIGH";

  return "LOW";
}

function normalizeMCPToolSchema(schema: any): any {
  return {
    type: schema.type,
    properties: normalizeProperties(schema.properties),
    required: schema.required,
    additionalProperties: schema.additionalProperties,
  };
}

function normalizeProperties(
  properties: Record<string, any>,
): Record<string, any> {
  const result: Record<string, any> = {};

  for (const [key, prop] of Object.entries(properties)) {
    result[key] = {
      type: prop.type,
      description: prop.description,
      default: prop.default,
      enum: prop.enum,
      format: prop.format,
      minimum: prop.minimum,
      maximum: prop.maximum,
      minLength: prop.minLength,
      maxLength: prop.maxLength,
      pattern: prop.pattern,
      items: prop.items ? normalizeProperty(prop.items) : undefined,
      properties: prop.properties
        ? normalizeProperties(prop.properties)
        : undefined,
      required: prop.required,
      additionalProperties:
        prop.additionalProperties === true
          ? true
          : prop.additionalProperties === false
            ? false
            : prop.additionalProperties
              ? normalizeProperty(prop.additionalProperties)
              : undefined,
    };
  }

  return result;
}

function normalizeProperty(prop: any): any {
  return {
    type: prop.type,
    description: prop.description,
    default: prop.default,
    enum: prop.enum,
    format: prop.format,
    minimum: prop.minimum,
    maximum: prop.maximum,
    minLength: prop.minLength,
    maxLength: prop.maxLength,
    pattern: prop.pattern,
    items: prop.items ? normalizeProperty(prop.items) : undefined,
    properties: prop.properties
      ? normalizeProperties(prop.properties)
      : undefined,
    required: prop.required,
    additionalProperties:
      prop.additionalProperties === true
        ? true
        : prop.additionalProperties === false
          ? false
          : prop.additionalProperties
            ? normalizeProperty(prop.additionalProperties)
            : undefined,
  };
}
