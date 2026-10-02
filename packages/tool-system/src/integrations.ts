import {
  ToolDefinition,
  ToolProvider,
  ToolCategory,
  ToolCapability,
  ToolRiskLevel,
  ToolExecutionMode,
  ToolExecutionContext,
  ToolResult,
  ToolAdapter,
  JSONSchema,
} from './types';
import { ToolRegistry } from './registry';
import { ToolExecutionRuntime } from './execution';
import { OpenAgentLogger, createChildLogger } from '@openagent/logger';

const logger: OpenAgentLogger = createChildLogger({ module: 'tool-system:integrations' });

export interface MCPToolDefinition {
  name: string;
  description: string;
  inputSchema: JSONSchema;
  outputSchema?: JSONSchema;
}

export interface MCPServerConfig {
  id: string;
  name: string;
  transport: 'stdio' | 'sse' | 'websocket';
  command?: string;
  args?: string[];
  url?: string;
  headers?: Record<string, string>;
  credentials?: Record<string, unknown>;
}

export interface MCPToolAdapter extends ToolAdapter {
  readonly adapter_id: 'mcp';
  readonly server_id: string;
  readonly supported_tool_types: ['mcp'];
  initialize(): Promise<void>;
  listTools(): Promise<MCPToolDefinition[]>;
  callTool(name: string, args: Record<string, unknown>): Promise<ToolResult>;
  close(): Promise<void>;
}

export class MCPIntegration {
  private registry: ToolRegistry;
  private runtime: ToolExecutionRuntime;
  private servers: Map<string, MCPToolAdapter> = new Map();
  private serverConfigs: Map<string, MCPServerConfig> = new Map();

  constructor(registry: ToolRegistry, runtime: ToolExecutionRuntime) {
    this.registry = registry;
    this.runtime = runtime;
  }

  async registerServer(config: MCPServerConfig): Promise<void> {
    logger.info('Registering MCP server', { server_id: config.id, transport: config.transport });

    const adapter = await this.createMCPAdapter(config);
    await adapter.initialize();

    this.servers.set(config.id, adapter);
    this.serverConfigs.set(config.id, config);

    // Register server as a tool provider
    const provider: ToolProvider = {
      id: `mcp-${config.id}`,
      name: config.name,
      provider_type: 'MCP',
      configuration: {
        transport: config.transport,
        command: config.command,
        args: config.args,
        url: config.url,
      },
      supported_tool_types: ['mcp'],
      health_status: 'UNKNOWN',
      created_at: new Date(),
      updated_at: new Date(),
    };
    this.registry.registerProvider(provider);

    // Register adapter
    this.runtime.registerAdapter(adapter);

    // Discover and register tools
    await this.discoverTools(config.id, adapter);
  }

  private async createMCPAdapter(config: MCPServerConfig): Promise<MCPToolAdapter> {
    // This would be implemented with actual MCP client library
    // For now, return a stub adapter
    return {
      adapter_id: 'mcp',
      server_id: config.id,
      supported_tool_types: ['mcp'],
      async initialize() {
        logger.info('MCP adapter initialized', { server_id: config.id });
      },
      async validate(_tool: ToolDefinition, _input: Record<string, unknown>) {
        return { valid: true, errors: [] };
      },
      async execute(_context: ToolExecutionContext, _input: Record<string, unknown>) {
        return {
          success: false,
          error: {
            code: 'PROVIDER_ERROR',
            message: 'MCP adapter not fully implemented',
            retryable: false,
          },
          metadata: { adapter: 'mcp', server_id: config.id },
          duration_ms: 0,
          retryable: false,
          truncated: false,
          artifacts: [],
        };
      },
      async cancel(executionId: string) {
        logger.info('MCP tool cancellation requested', { execution_id: executionId, server_id: config.id });
      },
      async listTools() {
        return [];
      },
      async callTool(name: string, args: Record<string, unknown>) {
        return {
          success: false,
          error: { code: 'PROVIDER_ERROR', message: 'Not implemented', retryable: false },
          metadata: {},
          duration_ms: 0,
          retryable: false,
          truncated: false,
          artifacts: [],
        };
      },
      async close() {
        logger.info('MCP adapter closed', { server_id: config.id });
      },
    };
  }

  private async discoverTools(serverId: string, adapter: MCPToolAdapter): Promise<void> {
    try {
      const tools = await adapter.listTools();
      for (const toolDef of tools) {
        const tool: ToolDefinition = {
          id: `mcp-${serverId}-${toolDef.name}`,
          slug: toolDef.name,
          metadata: {
            name: toolDef.name,
            display_name: toolDef.name,
            description: toolDef.description,
            category: 'custom',
            tags: ['mcp', serverId],
            documentation_url: undefined,
            provider: `mcp-${serverId}`,
            version: '1.0.0',
            capabilities: ['read'],
            risk_level: 'LOW',
            execution_mode: 'SYNC',
            timeout: 30000,
            supports_streaming: false,
            supports_cancellation: true,
            supports_idempotency: false,
            trust_level: 'COMMUNITY',
          },
          input_schema: toolDef.inputSchema,
          output_schema: toolDef.outputSchema,
          status: 'ACTIVE',
          configuration: { mcp_server: serverId, mcp_tool: toolDef.name },
          created_at: new Date(),
          updated_at: new Date(),
        };
        this.registry.register(tool);
      }
      logger.info('Discovered MCP tools', { server_id: serverId, count: tools.length });
    } catch (error) {
      logger.error('Failed to discover MCP tools', { server_id: serverId, error: String(error) });
    }
  }

  async unregisterServer(serverId: string): Promise<void> {
    const adapter = this.servers.get(serverId);
    if (adapter) {
      await adapter.close();
      this.servers.delete(serverId);
      this.serverConfigs.delete(serverId);
      logger.info('MCP server unregistered', { server_id: serverId });
    }
  }

  getServer(serverId: string): MCPToolAdapter | undefined {
    return this.servers.get(serverId);
  }

  listServers(): MCPServerConfig[] {
    return Array.from(this.serverConfigs.values());
  }
}

export interface BrowserToolDefinition {
  name: string;
  description: string;
  inputSchema: JSONSchema;
  outputSchema?: JSONSchema;
}

export interface BrowserToolAdapter extends ToolAdapter {
  readonly adapter_id: 'browser';
  readonly supported_tool_types: ['browser'];
  navigate(url: string, options?: { waitUntil?: 'load' | 'domcontentloaded' | 'networkidle' }): Promise<ToolResult>;
  click(selector: string, options?: { button?: 'left' | 'right' | 'middle'; clickCount?: number }): Promise<ToolResult>;
  type(selector: string, text: string, options?: { delay?: number }): Promise<ToolResult>;
  screenshot(options?: { fullPage?: boolean; format?: 'png' | 'jpeg'; quality?: number }): Promise<ToolResult>;
  extract(selector: string, attribute?: string): Promise<ToolResult>;
  evaluate(script: string): Promise<ToolResult>;
  close(): Promise<void>;
}

export class BrowserIntegration {
  private registry: ToolRegistry;
  private adapters: Map<string, BrowserToolAdapter> = new Map();

  constructor(registry: ToolRegistry) {
    this.registry = registry;
  }

  async registerBrowser(adapter: BrowserToolAdapter, browserId: string): Promise<void> {
    logger.info('Registering browser adapter', { browser_id: browserId });
    this.adapters.set(browserId, adapter);
    // this.runtime.registerAdapter(adapter); // Runtime registration handled externally

    // Register built-in browser tools
    const builtinTools = this.getBuiltinBrowserTools(browserId);
    for (const tool of builtinTools) {
      this.registry.register(tool);
    }
  }

  private getBuiltinBrowserTools(browserId: string): ToolDefinition[] {
    return [
      {
        id: `browser-${browserId}-open`,
        slug: 'browser.open',
        metadata: {
          name: 'browser.open',
          display_name: 'Browser Open',
          description: 'Navigate to a URL',
          icon: 'globe',
          category: 'browser',
          tags: ['browser', 'navigate', 'web'],
          documentation_url: 'https://docs.openagent.ai/tools/browser-open',
          provider: `browser-${browserId}`,
          version: '1.0.0',
          capabilities: ['network', 'browser_control', 'read'],
          risk_level: 'MEDIUM',
          execution_mode: 'SYNC',
          timeout: 60000,
          retry_policy: { max_attempts: 2, backoff: 1000, jitter: 500, retryable_errors: ['TOOL_TIMEOUT'] },
          supports_streaming: false,
          supports_cancellation: true,
          supports_idempotency: false,
          trust_level: 'ORGANIZATION',
        },
        input_schema: {
          type: 'object',
          properties: {
            url: { type: 'string', format: 'uri' },
            waitUntil: { type: 'string', enum: ['load', 'domcontentloaded', 'networkidle'], default: 'networkidle' },
          },
          required: ['url'],
        },
        output_schema: {
          type: 'object',
          properties: {
            url: { type: 'string' },
            title: { type: 'string' },
            status: { type: 'number' },
          },
        },
        status: 'ACTIVE',
        configuration: { browser_id: browserId },
        created_at: new Date(),
        updated_at: new Date(),
      },
      {
        id: `browser-${browserId}-click`,
        slug: 'browser.click',
        metadata: {
          name: 'browser.click',
          display_name: 'Browser Click',
          description: 'Click an element',
          icon: 'mouse-pointer',
          category: 'browser',
          tags: ['browser', 'click', 'interact'],
          provider: `browser-${browserId}`,
          version: '1.0.0',
          capabilities: ['browser_control', 'write'],
          risk_level: 'MEDIUM',
          execution_mode: 'SYNC',
          timeout: 30000,
          supports_streaming: false,
          supports_cancellation: true,
          supports_idempotency: false,
          trust_level: 'ORGANIZATION',
        },
        input_schema: {
          type: 'object',
          properties: {
            selector: { type: 'string' },
            button: { type: 'string', enum: ['left', 'right', 'middle'], default: 'left' },
            clickCount: { type: 'number', default: 1 },
          },
          required: ['selector'],
        },
        output_schema: {
          type: 'object',
          properties: {
            success: { type: 'boolean' },
          },
        },
        status: 'ACTIVE',
        configuration: { browser_id: browserId },
        created_at: new Date(),
        updated_at: new Date(),
      },
      {
        id: `browser-${browserId}-type`,
        slug: 'browser.type',
        metadata: {
          name: 'browser.type',
          display_name: 'Browser Type',
          description: 'Type text into an element',
          icon: 'keyboard',
          category: 'browser',
          tags: ['browser', 'type', 'input'],
          provider: `browser-${browserId}`,
          version: '1.0.0',
          capabilities: ['browser_control', 'write'],
          risk_level: 'MEDIUM',
          execution_mode: 'SYNC',
          timeout: 30000,
          supports_streaming: false,
          supports_cancellation: true,
          supports_idempotency: false,
          trust_level: 'ORGANIZATION',
        },
        input_schema: {
          type: 'object',
          properties: {
            selector: { type: 'string' },
            text: { type: 'string' },
            delay: { type: 'number', default: 0 },
          },
          required: ['selector', 'text'],
        },
        output_schema: {
          type: 'object',
          properties: {
            success: { type: 'boolean' },
          },
        },
        status: 'ACTIVE',
        configuration: { browser_id: browserId },
        created_at: new Date(),
        updated_at: new Date(),
      },
      {
        id: `browser-${browserId}-screenshot`,
        slug: 'browser.screenshot',
        metadata: {
          name: 'browser.screenshot',
          display_name: 'Browser Screenshot',
          description: 'Take a screenshot',
          icon: 'camera',
          category: 'browser',
          tags: ['browser', 'screenshot', 'capture'],
          provider: `browser-${browserId}`,
          version: '1.0.0',
          capabilities: ['browser_control', 'read'],
          risk_level: 'LOW',
          execution_mode: 'SYNC',
          timeout: 30000,
          supports_streaming: false,
          supports_cancellation: true,
          supports_idempotency: false,
          trust_level: 'ORGANIZATION',
        },
        input_schema: {
          type: 'object',
          properties: {
            fullPage: { type: 'boolean', default: false },
            format: { type: 'string', enum: ['png', 'jpeg'], default: 'png' },
            quality: { type: 'number', default: 80, minimum: 1, maximum: 100 },
          },
        },
        output_schema: {
          type: 'object',
          properties: {
            image: { type: 'string', format: 'binary' },
            format: { type: 'string' },
          },
        },
        status: 'ACTIVE',
        configuration: { browser_id: browserId },
        created_at: new Date(),
        updated_at: new Date(),
      },
      {
        id: `browser-${browserId}-extract`,
        slug: 'browser.extract',
        metadata: {
          name: 'browser.extract',
          display_name: 'Browser Extract',
          description: 'Extract data from page',
          icon: 'scissors',
          category: 'browser',
          tags: ['browser', 'extract', 'scrape'],
          provider: `browser-${browserId}`,
          version: '1.0.0',
          capabilities: ['browser_control', 'read'],
          risk_level: 'LOW',
          execution_mode: 'SYNC',
          timeout: 30000,
          supports_streaming: false,
          supports_cancellation: true,
          supports_idempotency: true,
          trust_level: 'ORGANIZATION',
        },
        input_schema: {
          type: 'object',
          properties: {
            selector: { type: 'string' },
            attribute: { type: 'string' },
          },
          required: ['selector'],
        },
        output_schema: {
          type: 'object',
          properties: {
            data: { type: ['string', 'array', 'object'] },
          },
        },
        status: 'ACTIVE',
        configuration: { browser_id: browserId },
        created_at: new Date(),
        updated_at: new Date(),
      },
    ];
  }

  async unregisterBrowser(browserId: string): Promise<void> {
    const adapter = this.adapters.get(browserId);
    if (adapter) {
      await adapter.close();
      this.adapters.delete(browserId);
      logger.info('Browser adapter unregistered', { browser_id: browserId });
    }
  }

  getBrowser(browserId: string): BrowserToolAdapter | undefined {
    return this.adapters.get(browserId);
  }
}

export interface CodingToolDefinition {
  name: string;
  description: string;
  inputSchema: JSONSchema;
  outputSchema?: JSONSchema;
}

export interface CodingToolAdapter extends ToolAdapter {
  readonly adapter_id: 'coding';
  readonly supported_tool_types: ['coding'];
  readFile(path: string): Promise<ToolResult>;
  writeFile(path: string, content: string): Promise<ToolResult>;
  listFiles(path: string): Promise<ToolResult>;
  searchCode(pattern: string, options?: { path?: string; filePattern?: string }): Promise<ToolResult>;
  applyPatch(patch: string): Promise<ToolResult>;
  runTests(options?: { pattern?: string; coverage?: boolean }): Promise<ToolResult>;
  executeCommand(command: string, args: string[], options?: { cwd?: string; timeout?: number }): Promise<ToolResult>;
  close(): Promise<void>;
}

export class CodingIntegration {
  private registry: ToolRegistry;
  private adapters: Map<string, CodingToolAdapter> = new Map();

  constructor(registry: ToolRegistry) {
    this.registry = registry;
  }

  async registerCodingAgent(adapter: CodingToolAdapter, agentId: string): Promise<void> {
    logger.info('Registering coding agent adapter', { agent_id: agentId });
    this.adapters.set(agentId, adapter);
    // this.runtime.registerAdapter(adapter); // Runtime registration handled externally

    const builtinTools = this.getBuiltinCodingTools(agentId);
    for (const tool of builtinTools) {
      this.registry.register(tool);
    }
  }

  private getBuiltinCodingTools(agentId: string): ToolDefinition[] {
    return [
      {
        id: `coding-${agentId}-read`,
        slug: 'repository.read',
        metadata: {
          name: 'repository.read',
          display_name: 'Read File',
          description: 'Read a file from the repository',
          icon: 'file',
          category: 'code',
          tags: ['code', 'read', 'file'],
          provider: `coding-${agentId}`,
          version: '1.0.0',
          capabilities: ['read', 'filesystem'],
          risk_level: 'LOW',
          execution_mode: 'SYNC',
          timeout: 10000,
          supports_streaming: false,
          supports_cancellation: true,
          supports_idempotency: true,
          trust_level: 'ORGANIZATION',
        },
        input_schema: {
          type: 'object',
          properties: {
            path: { type: 'string' },
            encoding: { type: 'string', default: 'utf-8' },
          },
          required: ['path'],
        },
        output_schema: {
          type: 'object',
          properties: {
            content: { type: 'string' },
            path: { type: 'string' },
            size: { type: 'number' },
          },
        },
        status: 'ACTIVE',
        configuration: { coding_agent: agentId },
        created_at: new Date(),
        updated_at: new Date(),
      },
      {
        id: `coding-${agentId}-write`,
        slug: 'repository.write',
        metadata: {
          name: 'repository.write',
          display_name: 'Write File',
          description: 'Write a file to the repository',
          icon: 'save',
          category: 'code',
          tags: ['code', 'write', 'file'],
          provider: `coding-${agentId}`,
          version: '1.0.0',
          capabilities: ['write', 'filesystem'],
          risk_level: 'MEDIUM',
          execution_mode: 'SYNC',
          timeout: 10000,
          supports_streaming: false,
          supports_cancellation: true,
          supports_idempotency: false,
          trust_level: 'ORGANIZATION',
        },
        input_schema: {
          type: 'object',
          properties: {
            path: { type: 'string' },
            content: { type: 'string' },
            encoding: { type: 'string', default: 'utf-8' },
          },
          required: ['path', 'content'],
        },
        output_schema: {
          type: 'object',
          properties: {
            success: { type: 'boolean' },
            path: { type: 'string' },
          },
        },
        status: 'ACTIVE',
        configuration: { coding_agent: agentId },
        created_at: new Date(),
        updated_at: new Date(),
      },
      {
        id: `coding-${agentId}-search`,
        slug: 'code.search',
        metadata: {
          name: 'code.search',
          display_name: 'Search Code',
          description: 'Search code in the repository',
          icon: 'search',
          category: 'code',
          tags: ['code', 'search', 'grep'],
          provider: `coding-${agentId}`,
          version: '1.0.0',
          capabilities: ['read', 'filesystem'],
          risk_level: 'LOW',
          execution_mode: 'SYNC',
          timeout: 30000,
          supports_streaming: false,
          supports_cancellation: true,
          supports_idempotency: true,
          trust_level: 'ORGANIZATION',
        },
        input_schema: {
          type: 'object',
          properties: {
            pattern: { type: 'string' },
            path: { type: 'string' },
            filePattern: { type: 'string' },
            caseSensitive: { type: 'boolean', default: false },
          },
          required: ['pattern'],
        },
        output_schema: {
          type: 'object',
          properties: {
            results: {
              type: 'array',
              items: {
                type: 'object',
                properties: {
                  file: { type: 'string' },
                  line: { type: 'number' },
                  column: { type: 'number' },
                  match: { type: 'string' },
                },
              },
            },
          },
        },
        status: 'ACTIVE',
        configuration: { coding_agent: agentId },
        created_at: new Date(),
        updated_at: new Date(),
      },
    ];
  }

  async unregisterCodingAgent(agentId: string): Promise<void> {
    const adapter = this.adapters.get(agentId);
    if (adapter) {
      await adapter.close();
      this.adapters.delete(agentId);
      logger.info('Coding agent adapter unregistered', { agent_id: agentId });
    }
  }

  getCodingAgent(agentId: string): CodingToolAdapter | undefined {
    return this.adapters.get(agentId);
  }
}

export interface MarketplacePackage {
  id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  tools: MarketplaceTool[];
  metadata: Record<string, unknown>;
}

export interface MarketplaceTool {
  slug: string;
  name: string;
  description: string;
  category: ToolCategory;
  input_schema: JSONSchema;
  output_schema?: JSONSchema;
  capabilities: ToolCapability[];
  risk_level: ToolRiskLevel;
  execution_mode: ToolExecutionMode;
  timeout: number;
  configuration: Record<string, unknown>;
}

export class MarketplaceIntegration {
  private registry: ToolRegistry;
  private installedPackages: Map<string, MarketplacePackage> = new Map();

  constructor(registry: ToolRegistry) {
    this.registry = registry;
  }

  async installPackage(pkg: MarketplacePackage): Promise<void> {
    logger.info('Installing marketplace package', { package_id: pkg.id, version: pkg.version });

    // Validate package
    this.validatePackage(pkg);

    // Register tools from package
    for (const toolDef of pkg.tools) {
      const tool: ToolDefinition = {
        id: `marketplace-${pkg.id}-${toolDef.slug}`,
        slug: toolDef.slug,
        metadata: {
          name: toolDef.name,
          display_name: toolDef.name,
          description: toolDef.description,
          category: toolDef.category,
          tags: ['marketplace', pkg.id],
          documentation_url: undefined,
          provider: `marketplace-${pkg.id}`,
          version: pkg.version,
          capabilities: toolDef.capabilities,
          risk_level: toolDef.risk_level,
          execution_mode: toolDef.execution_mode,
          timeout: toolDef.timeout,
          retry_policy: { max_attempts: 2, backoff: 1000, jitter: 500, retryable_errors: ['TOOL_TIMEOUT'] },
          supports_streaming: false,
          supports_cancellation: true,
          supports_idempotency: false,
          trust_level: 'COMMUNITY',
        },
        input_schema: toolDef.input_schema,
        output_schema: toolDef.output_schema,
        status: 'ACTIVE',
        configuration: toolDef.configuration,
        created_at: new Date(),
        updated_at: new Date(),
      };
      this.registry.register(tool);
    }

    this.installedPackages.set(pkg.id, pkg);
    logger.info('Marketplace package installed', { package_id: pkg.id, tools_count: pkg.tools.length });
  }

  private validatePackage(pkg: MarketplacePackage): void {
    if (!pkg.tools || pkg.tools.length === 0) {
      throw new Error('Package must contain at least one tool');
    }
    for (const tool of pkg.tools) {
      if (!tool.slug || !tool.name) {
        throw new Error('Each tool must have slug and name');
      }
      if (!tool.input_schema) {
        throw new Error(`Tool ${tool.slug} must have input_schema`);
      }
    }
  }

  async uninstallPackage(packageId: string): Promise<void> {
    const pkg = this.installedPackages.get(packageId);
    if (pkg) {
      for (const tool of pkg.tools) {
        this.registry.unregister(`marketplace-${packageId}-${tool.slug}`, pkg.version);
      }
      this.installedPackages.delete(packageId);
      logger.info('Marketplace package uninstalled', { package_id: packageId });
    }
  }

  getInstalledPackages(): MarketplacePackage[] {
    return Array.from(this.installedPackages.values());
  }

  getPackage(packageId: string): MarketplacePackage | undefined {
    return this.installedPackages.get(packageId);
  }
}

export function createMCPIntegration(registry: ToolRegistry, runtime: ToolExecutionRuntime): MCPIntegration {
  return new MCPIntegration(registry, runtime);
}

export function createBrowserIntegration(registry: ToolRegistry): BrowserIntegration {
  return new BrowserIntegration(registry);
}

export function createCodingIntegration(registry: ToolRegistry): CodingIntegration {
  return new CodingIntegration(registry);
}

export function createMarketplaceIntegration(registry: ToolRegistry): MarketplaceIntegration {
  return new MarketplaceIntegration(registry);
}