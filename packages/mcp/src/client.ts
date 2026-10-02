import { EventEmitter } from "events";
import { MCPTransport, createTransportFactory } from "./transport";
import {
  MCPServerConfig,
  MCPConnection,
  MCPConnectionState,
  MCPCapabilities,
  MCPServerInfo,
  MCPTool,
  MCPResource,
  MCPPrompt,
  MCPToolCall,
  MCPToolResult,
  MCPListToolsResult,
  MCPListResourcesResult,
  MCPReadResourceResult,
  MCPListPromptsResult,
  MCPGetPromptResult,
  MCPInitializeResult,
  MCPError,
  MCPTransportType,
  MCPCredential,
  MCPHealthRecord,
} from "./types";
import { OpenAgentLogger, createChildLogger } from "@openagent/logger";

const logger = createChildLogger({ module: "mcp:client" });

export interface MCPClientOptions {
  serverConfig: MCPServerConfig;
  credentialResolver: (credentialId: string) => Promise<MCPCredential | null>;
  onCapabilitiesChange?: (capabilities: MCPCapabilities) => void;
  onStateChange?: (state: MCPConnectionState) => void;
  onError?: (error: Error) => void;
  onNotification?: (notification: { method: string; params?: unknown }) => void;
}

export class MCPClient extends EventEmitter {
  private transport: MCPTransport;
  private serverConfig: MCPServerConfig;
  private credentialResolver: (
    credentialId: string,
  ) => Promise<MCPCredential | null>;
  private connection: MCPConnection;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private healthCheckInterval?: NodeJS.Timeout;
  private readonly maxHealthCheckInterval = 60000;
  private readonly minHealthCheckInterval = 5000;

  constructor(options: MCPClientOptions) {
    super();
    this.serverConfig = options.serverConfig;
    this.credentialResolver = options.credentialResolver;
    this.transport = createTransportFactory().createTransport(
      this.serverConfig.transport,
      this.serverConfig,
    );
    this.connection = {
      id: crypto.randomUUID(),
      server_id: this.serverConfig.id,
      state: "DISCONNECTED",
      capabilities: {},
      created_at: new Date(),
      last_activity: new Date(),
    };

    this.setupTransportListeners();

    if (options.onCapabilitiesChange) {
      this.on("capabilities", options.onCapabilitiesChange);
    }
    if (options.onStateChange) {
      this.on("stateChange", options.onStateChange);
    }
    if (options.onError) {
      this.on("error", options.onError);
    }
    if (options.onNotification) {
      this.on("notification", options.onNotification);
    }
  }

  private setupTransportListeners(): void {
    this.transport.on("close", (error?: Error) => {
      this.handleDisconnect(error);
    });

    this.transport.on("error", (error: Error) => {
      logger.error("Transport error", {
        server_id: this.serverConfig.id,
        error: error.message,
      });
      this.emit("error", error);
    });

    this.transport.on(
      "notification",
      (notification: { method: string; params?: unknown }) => {
        this.emit("notification", notification);
      },
    );

    this.transport.on("capabilities", (capabilities: MCPCapabilities) => {
      this.connection.capabilities = capabilities;
      this.emit("capabilities", capabilities);
    });
  }

  async connect(): Promise<MCPConnection> {
    if (
      this.connection.state === "CONNECTING" ||
      this.connection.state === "CONNECTED"
    ) {
      return this.connection;
    }

    this.connection.state = "CONNECTING";
    this.emit("stateChange", "CONNECTING");

    try {
      await this.injectCredentials();
      await this.transport.connect(this.serverConfig);

      this.connection.state = "CONNECTED";
      this.connection.last_activity = new Date();
      this.reconnectAttempts = 0;

      await this.discoverCapabilities();

      this.startHealthChecks();

      logger.info("MCP client connected", {
        server_id: this.serverConfig.id,
        tools: this.connection.capabilities.tools?.list_changed
          ? "discovered"
          : "none",
        resources: this.connection.capabilities.resources
          ? "available"
          : "none",
        prompts: this.connection.capabilities.prompts ? "available" : "none",
      });

      this.emit("stateChange", "CONNECTED");
      return this.connection;
    } catch (error) {
      this.connection.state = "FAILED";
      this.emit("stateChange", "FAILED");
      throw error;
    }
  }

  private async injectCredentials(): Promise<void> {
    if (!this.serverConfig.credential_id) return;

    const credential = await this.credentialResolver(
      this.serverConfig.credential_id,
    );
    if (!credential) {
      throw new Error(
        `Credential ${this.serverConfig.credential_id} not found`,
      );
    }

    // Inject credential into transport config
    if (
      this.serverConfig.transport === "streamable_http" ||
      this.serverConfig.transport === "sse"
    ) {
      const authHeader = this.buildAuthHeader(credential);
      if (authHeader) {
        this.serverConfig.configuration = {
          ...this.serverConfig.configuration,
          auth_header: authHeader,
        };
      }
    }
  }

  private buildAuthHeader(credential: MCPCredential): string | null {
    switch (credential.type) {
      case "api_key":
        return `Bearer ${credential.data.api_key}`;
      case "bearer_token":
        return `Bearer ${credential.data.token}`;
      case "basic_auth":
        const encoded = Buffer.from(
          `${credential.data.username}:${credential.data.password}`,
        ).toString("base64");
        return `Basic ${encoded}`;
      case "oauth_token":
        return `Bearer ${credential.data.access_token}`;
      default:
        return null;
    }
  }

  private async discoverCapabilities(): Promise<void> {
    const [tools, resources, prompts] = await Promise.allSettled([
      this.listTools(),
      this.listResources(),
      this.listPrompts(),
    ]);

    this.connection.capabilities = {
      tools: tools.status === "fulfilled" ? { list_changed: true } : undefined,
      resources:
        resources.status === "fulfilled"
          ? { subscribe: true, list_changed: true }
          : undefined,
      prompts:
        prompts.status === "fulfilled" ? { list_changed: true } : undefined,
    };

    if (tools.status === "fulfilled") {
      logger.debug("Discovered MCP tools", {
        server_id: this.serverConfig.id,
        count: tools.value.tools.length,
      });
    }
    if (resources.status === "fulfilled") {
      logger.debug("Discovered MCP resources", {
        server_id: this.serverConfig.id,
        count: resources.value.resources.length,
      });
    }
    if (prompts.status === "fulfilled") {
      logger.debug("Discovered MCP prompts", {
        server_id: this.serverConfig.id,
        count: prompts.value.prompts.length,
      });
    }
  }

  async disconnect(): Promise<void> {
    this.stopHealthChecks();
    await this.transport.disconnect();
    this.connection.state = "DISCONNECTED";
    this.emit("stateChange", "DISCONNECTED");
    logger.info("MCP client disconnected", { server_id: this.serverConfig.id });
  }

  private handleDisconnect(error?: Error): void {
    this.stopHealthChecks();
    this.connection.state = "DISCONNECTED";
    this.emit("stateChange", "DISCONNECTED");

    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.scheduleReconnect();
    } else {
      logger.error("Max reconnect attempts reached", {
        server_id: this.serverConfig.id,
      });
      this.connection.state = "FAILED";
      this.emit("stateChange", "FAILED");
    }
  }

  private scheduleReconnect(): void {
    const delay =
      this.reconnectDelay * Math.pow(2, this.reconnectAttempts) +
      Math.random() * 1000;
    this.reconnectAttempts++;

    logger.info("Scheduling MCP reconnect", {
      server_id: this.serverConfig.id,
      attempt: this.reconnectAttempts,
      delay_ms: delay,
    });

    setTimeout(() => {
      this.connect().catch((error) => {
        logger.error("MCP reconnect failed", {
          server_id: this.serverConfig.id,
          error: error.message,
        });
        this.handleDisconnect(error);
      });
    }, delay);
  }

  private startHealthChecks(): void {
    this.stopHealthChecks();

    this.healthCheckInterval = setInterval(async () => {
      try {
        await this.ping();
        this.connection.last_activity = new Date();
      } catch (error) {
        logger.warn("MCP health check failed", {
          server_id: this.serverConfig.id,
          error: String(error),
        });
        this.connection.state = "DEGRADED";
        this.emit("stateChange", "DEGRADED");
      }
    }, this.minHealthCheckInterval);
  }

  private stopHealthChecks(): void {
    if (this.healthCheckInterval) {
      clearInterval(this.healthCheckInterval);
      this.healthCheckInterval = undefined;
    }
  }

  async ping(): Promise<void> {
    await this.transport.send({
      jsonrpc: "2.0",
      id: this.generateRequestId(),
      method: "ping",
    });
  }

  // Tool operations
  async listTools(cursor?: string): Promise<MCPListToolsResult> {
    const response = await this.transport.send({
      jsonrpc: "2.0",
      id: this.generateRequestId(),
      method: "tools/list",
      params: cursor ? { cursor } : undefined,
    });

    return response.result as MCPListToolsResult;
  }

  async callTool(
    name: string,
    arguments_: Record<string, unknown>,
  ): Promise<MCPToolResult> {
    const response = await this.transport.send({
      jsonrpc: "2.0",
      id: this.generateRequestId(),
      method: "tools/call",
      params: { name, arguments: arguments_ },
    });

    if (response.error) {
      throw new MCPProtocolError(response.error);
    }

    return response.result as MCPToolResult;
  }

  // Resource operations
  async listResources(cursor?: string): Promise<MCPListResourcesResult> {
    const response = await this.transport.send({
      jsonrpc: "2.0",
      id: this.generateRequestId(),
      method: "resources/list",
      params: cursor ? { cursor } : undefined,
    });

    return response.result as MCPListResourcesResult;
  }

  async readResource(uri: string): Promise<MCPReadResourceResult> {
    const response = await this.transport.send({
      jsonrpc: "2.0",
      id: this.generateRequestId(),
      method: "resources/read",
      params: { uri },
    });

    if (response.error) {
      throw new MCPProtocolError(response.error);
    }

    return response.result as MCPReadResourceResult;
  }

  // Prompt operations
  async listPrompts(cursor?: string): Promise<MCPListPromptsResult> {
    const response = await this.transport.send({
      jsonrpc: "2.0",
      id: this.generateRequestId(),
      method: "prompts/list",
      params: cursor ? { cursor } : undefined,
    });

    return response.result as MCPListPromptsResult;
  }

  async getPrompt(
    name: string,
    arguments_?: Record<string, unknown>,
  ): Promise<MCPGetPromptResult> {
    const response = await this.transport.send({
      jsonrpc: "2.0",
      id: this.generateRequestId(),
      method: "prompts/get",
      params: { name, arguments: arguments_ },
    });

    if (response.error) {
      throw new MCPProtocolError(response.error);
    }

    return response.result as MCPGetPromptResult;
  }

  // Health and monitoring
  async getHealth(): Promise<MCPHealthRecord> {
    return {
      server_id: this.serverConfig.id,
      status: this.mapConnectionState(this.connection.state),
      last_check: new Date(),
      connection_success: 0,
      connection_failure: this.reconnectAttempts,
      tool_success: 0,
      tool_failure: 0,
      resource_reads: 0,
      prompt_reads: 0,
      avg_latency_ms: 0,
      timeouts: 0,
      protocol_errors: 0,
    };
  }

  private mapConnectionState(
    state: MCPConnectionState,
  ): MCPHealthRecord["status"] {
    switch (state) {
      case "CONNECTED":
        return "HEALTHY";
      case "DEGRADED":
        return "DEGRADED";
      case "CONNECTING":
        return "UNKNOWN";
      case "DISCONNECTED":
      case "FAILED":
        return "UNAVAILABLE";
    }
  }

  getConnection(): MCPConnection {
    return { ...this.connection };
  }

  getServerConfig(): MCPServerConfig {
    return { ...this.serverConfig };
  }

  isConnected(): boolean {
    return this.connection.state === "CONNECTED";
  }

  private generateRequestId(): string {
    return crypto.randomUUID();
  }

  async refreshCapabilities(): Promise<void> {
    if (!this.isConnected()) {
      throw new Error("Cannot refresh capabilities: not connected");
    }
    await this.discoverCapabilities();
  }
}

export class MCPProtocolError extends Error {
  public readonly code: number;
  public readonly data?: unknown;

  constructor(error: MCPError) {
    super(error.message);
    this.name = "MCPProtocolError";
    this.code = error.code;
    this.data = error.data;
  }
}

export class MCPClientManager extends EventEmitter {
  private clients = new Map<string, MCPClient>();
  private credentialResolver: (
    credentialId: string,
  ) => Promise<MCPCredential | null>;

  constructor(
    credentialResolver: (credentialId: string) => Promise<MCPCredential | null>,
  ) {
    super();
    this.credentialResolver = credentialResolver;
  }

  async createClient(config: MCPServerConfig): Promise<MCPClient> {
    if (this.clients.has(config.id)) {
      throw new Error(`MCP client for server ${config.id} already exists`);
    }

    const client = new MCPClient({
      serverConfig: config,
      credentialResolver: this.credentialResolver,
      onCapabilitiesChange: (capabilities) => {
        this.emit("capabilitiesChange", config.id, capabilities);
      },
      onStateChange: (state) => {
        this.emit("stateChange", config.id, state);
      },
      onError: (error) => {
        this.emit("error", config.id, error);
      },
      onNotification: (notification) => {
        this.emit("notification", config.id, notification);
      },
    });

    this.clients.set(config.id, client);
    return client;
  }

  async getClient(serverId: string): Promise<MCPClient | undefined> {
    return this.clients.get(serverId);
  }

  async removeClient(serverId: string): Promise<void> {
    const client = this.clients.get(serverId);
    if (client) {
      await client.disconnect();
      this.clients.delete(serverId);
    }
  }

  listClients(): MCPClient[] {
    return Array.from(this.clients.values());
  }

  async connectAll(): Promise<void> {
    for (const client of this.clients.values()) {
      try {
        await client.connect();
      } catch (error) {
        logger.error("Failed to connect MCP client", {
          server_id: client.getServerConfig().id,
          error: String(error),
        });
      }
    }
  }

  async disconnectAll(): Promise<void> {
    for (const client of this.clients.values()) {
      await client.disconnect();
    }
    this.clients.clear();
  }
}
