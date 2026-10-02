import { EventEmitter } from 'events';
import { MCPClientManager, MCPClient } from './client';
import { MCPToolAdapter, createMCPToolDefinition } from './adapter';
import {
  MCPServerConfig,
  MCPServerScope,
  MCPTrustLevel,
  MCPTransportType,
  MCPCapabilities,
  MCPTool,
  MCPHealthRecord,
  MCPInstallationRequest,
  MCPConnectionTestResult,
  MCPRefreshResult,
  MCPPolicy,
  MCPErrorCodes,
} from './types';
import { ToolRegistry } from '../tool-system/src/registry';
import { ToolExecutionRuntime } from '../tool-system/src/execution';
import { ToolDefinition, ToolCategory, ToolLifecycleStatus } from '../tool-system/src/types';
import { PolicyEngine } from '../tool-system/src/policy';
import { RiskEngine } from '../tool-system/src/risk';
import { CredentialResolver } from '../tool-system/src/credentials';
import { OpenAgentLogger, createChildLogger } from '@openagent/logger';

const logger = createChildLogger({ module: 'mcp:registry' });

export interface MCPServerRegistryOptions {
  toolRegistry: ToolRegistry;
  executionRuntime: ToolExecutionRuntime;
  policyEngine: PolicyEngine;
  riskEngine: RiskEngine;
  credentialResolver: CredentialResolver;
}

export interface MCPServerRecord extends MCPServerConfig {
  id: string;
  created_at: Date;
  updated_at: Date;
  last_connected_at?: Date;
  connection_error?: string;
  capability_version: number;
}

export class MCPServerRegistry extends EventEmitter {
  private clientManager: MCPClientManager;
  private toolRegistry: ToolRegistry;
  private executionRuntime: ToolExecutionRuntime;
  private policyEngine: PolicyEngine;
  private riskEngine: RiskEngine;
  private servers = new Map<string, MCPServerRecord>();
  private adapters = new Map<string, { adapter: import('./adapter').MCPToolAdapter; tools: string[] }>();
  private healthRecords = new Map<string, MCPHealthRecord>();
  private policies = new Map<string, MCPPolicy>();

  constructor(options: MCPServerRegistryOptions) {
    super();
    this.toolRegistry = options.toolRegistry;
    this.executionRuntime = options.executionRuntime;
    this.policyEngine = options.policyEngine;
    this.riskEngine = options.riskEngine;

    this.clientManager = new MCPClientManager(
      async (credentialId) => {
        const cred = await options.credentialResolver.resolve(credentialId);
        return cred as unknown as import('./types').MCPCredential;
      }
    );

    this.setupClientManagerListeners();
  }

  private setupClientManagerListeners(): void {
    this.clientManager.on('stateChange', (serverId, state) => {
      this.emit('serverStateChange', serverId, state);
      this.updateHealthRecord(serverId, { status: state === 'CONNECTED' ? 'HEALTHY' : 'UNAVAILABLE' });
    });

    this.clientManager.on('capabilitiesChange', (serverId, capabilities) => {
      this.handleCapabilitiesChange(serverId, capabilities);
    });

    this.clientManager.on('error', (serverId, error) => {
      this.emit('serverError', serverId, error);
    });
  }

  async installServer(request: MCPInstallationRequest, organizationId: string, userId: string): Promise<MCPServerRecord> {
    // Validate request
    this.validateInstallationRequest(request);

    // Check policy
    await this.checkInstallationPolicy(organizationId, request);

    // Create server record
    const serverId = `mcp-${crypto.randomUUID().slice(0, 8)}`;
    const serverRecord: MCPServerRecord = {
      id: serverId,
      name: request.name,
      display_name: request.display_name,
      description: request.description,
      organization_id: organizationId,
      scope: request.scope,
      transport: request.transport,
      endpoint: request.endpoint,
      command: request.command,
      args: request.args,
      env: request.env,
      credential_id: request.credential_id,
      trust_level: request.trust_level,
      enabled: false,
      metadata: {},
      created_at: new Date(),
      updated_at: new Date(),
      capability_version: 0,
    };

    this.servers.set(serverId, serverRecord);
    this.emit('serverInstalled', serverRecord);

    logger.info('MCP server installed', { server_id: serverId, name: request.name });

    return serverRecord;
  }

  private validateInstallationRequest(request: MCPInstallationRequest): void {
    if (!request.name || request.name.length < 1 || request.name.length > 100) {
      throw new Error('Invalid server name');
    }

    if (!request.transport) {
      throw new Error('Transport is required');
    }

    if (request.transport === 'streamable_http' || request.transport === 'sse') {
      if (!request.endpoint) {
        throw new Error('Endpoint is required for HTTP/SSE transport');
      }
      try {
        new URL(request.endpoint);
      } catch {
        throw new Error('Invalid endpoint URL');
      }
    } else if (request.transport === 'stdio') {
      if (!request.command) {
        throw new Error('Command is required for stdio transport');
      }
    }

    const validTrustLevels: MCPTrustLevel[] = ['CORE', 'VERIFIED', 'ORGANIZATION', 'COMMUNITY', 'UNTRUSTED'];
    if (!validTrustLevels.includes(request.trust_level)) {
      throw new Error('Invalid trust level');
    }

    const validScopes: MCPServerScope[] = ['PLATFORM', 'ORGANIZATION', 'TEAM', 'USER'];
    if (!validScopes.includes(request.scope)) {
      throw new Error('Invalid scope');
    }
  }

  private async checkInstallationPolicy(organizationId: string, request: MCPInstallationRequest): Promise<void> {
    // Check if organization policy allows this server
    const policies = this.getPoliciesForOrganization(organizationId);
    
    for (const policy of policies) {
      if (policy.blocked_servers.includes(request.name)) {
        throw new Error(`Server ${request.name} is blocked by policy`);
      }
      
      if (policy.allowed_servers.length > 0 && !policy.allowed_servers.includes(request.name)) {
        throw new Error(`Server ${request.name} is not in allowed list`);
      }

      if (!policy.allowed_trust_levels.includes(request.trust_level)) {
        throw new Error(`Trust level ${request.trust_level} is not allowed`);
      }

      if (request.transport === 'streamable_http' || request.transport === 'sse') {
        if (request.endpoint) {
          const domain = new URL(request.endpoint).hostname;
          if (policy.blocked_domains.includes(domain)) {
            throw new Error(`Domain ${domain} is blocked`);
          }
          if (policy.allowed_domains.length > 0 && !policy.allowed_domains.includes(domain)) {
            throw new Error(`Domain ${domain} is not in allowed list`);
          }
        }
      }
    }
  }

  async activateServer(serverId: string): Promise<void> {
    const server = this.servers.get(serverId);
    if (!server) {
      throw new Error('Server not found');
    }

    if (server.enabled) {
      return; // Already active
    }

    // Create and connect client
    const client = await this.clientManager.createClient(server);
    await client.connect();

    // Create tool adapter
    const adapter = new MCPToolAdapter({
      serverId,
      serverName: server.name,
      client,
    });

    // Register tools
    const tools = await this.discoverAndRegisterTools(serverId, server.name, client);
    
    this.adapters.set(serverId, { adapter, tools });
    
    // Register adapter with execution runtime
    this.executionRuntime.registerAdapter(adapter);

    server.enabled = true;
    server.last_connected_at = new Date();
    server.updated_at = new Date();

    logger.info('MCP server activated', { server_id: serverId, tools_count: tools.length });
    this.emit('serverActivated', server);
  }

  async deactivateServer(serverId: string): Promise<void> {
    const server = this.servers.get(serverId);
    if (!server) {
      throw new Error('Server not found');
    }

    if (!server.enabled) {
      return; // Already inactive
    }

    // Unregister tools
    const adapterInfo = this.adapters.get(serverId);
    if (adapterInfo) {
      for (const toolId of adapterInfo.tools) {
        this.toolRegistry.unregister(toolId, '1.0.0');
      }
      this.adapters.delete(serverId);
    }

    // Disconnect client
    await this.clientManager.removeClient(serverId);

    server.enabled = false;
    server.updated_at = new Date();

    logger.info('MCP server deactivated', { server_id: serverId });
    this.emit('serverDeactivated', server);
  }

  async testConnection(request: MCPInstallationRequest): Promise<MCPConnectionTestResult> {
    const startTime = Date.now();
    const testServerId = `test-${crypto.randomUUID().slice(0, 8)}`;

    const testConfig: import('./types').MCPServerConfig = {
      id: testServerId,
      name: request.name,
      display_name: request.display_name,
      description: request.description,
      organization_id: '',
      scope: request.scope,
      transport: request.transport,
      endpoint: request.endpoint,
      command: request.command,
      args: request.args,
      env: request.env,
      credential_id: request.credential_id,
      trust_level: request.trust_level,
      enabled: true,
      metadata: {},
      created_at: new Date(),
      updated_at: new Date(),
    };

    try {
      const client = await this.clientManager.createClient(testConfig);
      await client.connect();

      const serverInfo = client.getConnection().server_info;
      const capabilities = client.getConnection().capabilities;

      let toolsCount = 0;
      let resourcesCount = 0;
      let promptsCount = 0;

      if (capabilities.tools) {
        const tools = await client.listTools();
        toolsCount = tools.tools.length;
      }
      if (capabilities.resources) {
        const resources = await client.listResources();
        resourcesCount = resources.resources.length;
      }
      if (capabilities.prompts) {
        const prompts = await client.listPrompts();
        promptsCount = prompts.prompts.length;
      }

      await client.disconnect();

      return {
        success: true,
        server_info: serverInfo,
        capabilities,
        tools_count: toolsCount,
        resources_count: resourcesCount,
        prompts_count: promptsCount,
        latency_ms: Date.now() - startTime,
      };
    } catch (error) {
      return {
        success: false,
        error: String(error),
        tools_count: 0,
        resources_count: 0,
        prompts_count: 0,
        latency_ms: Date.now() - startTime,
      };
    }
  }

  async refreshServer(serverId: string): Promise<MCPRefreshResult> {
    const server = this.servers.get(serverId);
    if (!server) {
      throw new Error('Server not found');
    }

    const client = await this.clientManager.getClient(serverId);
    if (!client) {
      throw new Error('Server not connected');
    }

    const result: MCPRefreshResult = {
      tools_added: [],
      tools_removed: [],
      tools_updated: [],
      resources_added: [],
      resources_removed: [],
      resources_updated: [],
      prompts_added: [],
      prompts_removed: [],
      prompts_updated: [],
    };

    // Refresh tools
    const adapterInfo = this.adapters.get(serverId);
    if (adapterInfo && adapterInfo.tools.length > 0) {
      const client = await this.clientManager.getClient(serverId);
      if (client) {
        const tools = await client.listTools();
        const currentTools = new Set(adapterInfo.tools);
        const newTools = new Set(tools.tools.map(t => `mcp-${serverId}-${t.name}`));

        // Find removed tools
        for (const toolId of currentTools) {
          if (!newTools.has(toolId)) {
            result.tools_removed.push(toolId);
            this.toolRegistry.unregister(toolId, '1.0.0');
          }
        }

        // Find added/updated tools
        for (const tool of tools.tools) {
          const toolId = `mcp-${serverId}-${tool.name}`;
          if (!currentTools.has(toolId)) {
            result.tools_added.push(toolId);
            const toolDef = createMCPToolDefinition(serverId, server.name, tool);
            this.toolRegistry.register(toolDef);
            adapterInfo.tools.push(toolId);
          } else {
            // Check for schema changes
            const existingTool = this.toolRegistry.get(toolId, '1.0.0');
            if (existingTool && JSON.stringify(existingTool.input_schema) !== JSON.stringify(tool.inputSchema)) {
              result.tools_updated.push(toolId);
              const toolDef = createMCPToolDefinition(serverId, server.name, tool);
              this.toolRegistry.unregister(toolId, '1.0.0');
              this.toolRegistry.register(toolDef);
            }
          }
        }
      }
    }

    server.capability_version++;
    server.updated_at = new Date();

    logger.info('MCP server refreshed', { server_id: serverId, ...result });
    return result;
  }

  async healthCheck(serverId: string): Promise<MCPHealthRecord> {
    const server = this.servers.get(serverId);
    if (!server) {
      throw new Error('Server not found');
    }

    const client = await this.clientManager.getClient(serverId);
    if (!client) {
      const health: MCPHealthRecord = {
        server_id: serverId,
        status: 'UNAVAILABLE',
        last_check: new Date(),
        connection_success: 0,
        connection_failure: 1,
        tool_success: 0,
        tool_failure: 0,
        resource_reads: 0,
        prompt_reads: 0,
        avg_latency_ms: 0,
        timeouts: 0,
        protocol_errors: 0,
      };
      this.healthRecords.set(serverId, health);
      return health;
    }

    const health = await client.getHealth();
    this.healthRecords.set(serverId, health);
    return health;
  }

  private async discoverAndRegisterTools(serverId: string, serverName: string, client: MCPClient): Promise<string[]> {
    const tools: string[] = [];

    if (!client.getConnection().capabilities.tools) {
      return tools;
    }

    const mcpTools = await client.listTools();
    
    for (const mcpTool of mcpTools.tools) {
      const toolDef = createMCPToolDefinition(serverId, serverName, mcpTool);
      this.toolRegistry.register(toolDef);
      tools.push(toolDef.id);
    }

    logger.info('MCP tools registered', { server_id: serverId, count: tools.length });
    return tools;
  }

  private async handleCapabilitiesChange(serverId: string, capabilities: import('./types').MCPCapabilities): Promise<void> {
    // Auto-refresh tools if tools capability changed
    if (capabilities.tools) {
      await this.refreshServer(serverId);
    }
  }

  private updateHealthRecord(serverId: string, partial: Partial<MCPHealthRecord>): void {
    const existing = this.healthRecords.get(serverId) || {
      server_id: serverId,
      status: 'UNKNOWN',
      last_check: new Date(),
      connection_success: 0,
      connection_failure: 0,
      tool_success: 0,
      tool_failure: 0,
      resource_reads: 0,
      prompt_reads: 0,
      avg_latency_ms: 0,
      timeouts: 0,
      protocol_errors: 0,
    };
    
    this.healthRecords.set(serverId, { ...existing, ...partial, last_check: new Date() });
  }

  getServer(serverId: string): MCPServerRecord | undefined {
    return this.servers.get(serverId);
  }

  listServers(organizationId?: string, scope?: MCPServerScope): MCPServerRecord[] {
    let servers = Array.from(this.servers.values());
    
    if (organizationId) {
      servers = servers.filter(s => s.organization_id === organizationId);
    }
    
    if (scope) {
      servers = servers.filter(s => s.scope === scope);
    }
    
    return servers;
  }

  getAdapter(serverId: string): import('./adapter').MCPToolAdapter | undefined {
    return this.adapters.get(serverId)?.adapter;
  }

  getHealth(serverId: string): MCPHealthRecord | undefined {
    return this.healthRecords.get(serverId);
  }

  // Policy management
  setPolicy(policy: MCPPolicy): void {
    this.policies.set(policy.id, policy);
  }

  getPolicy(policyId: string): MCPPolicy | undefined {
    return this.policies.get(policyId);
  }

  getPoliciesForOrganization(organizationId: string): MCPPolicy[] {
    return Array.from(this.policies.values()).filter(p => p.organization_id === organizationId);
  }

  async checkPolicy(serverId: string, toolName: string, organizationId: string): Promise<{ allowed: boolean; requiresApproval: boolean; reason?: string }> {
    const policies = this.getPoliciesForOrganization(organizationId);
    
    for (const policy of policies) {
      if (!policy.is_active) continue;

      if (policy.blocked_servers.includes(serverId)) {
        return { allowed: false, requiresApproval: false, reason: 'Server blocked by policy' };
      }

      if (policy.allowed_servers.length > 0 && !policy.allowed_servers.includes(serverId)) {
        return { allowed: false, requiresApproval: false, reason: 'Server not in allowed list' };
      }

      if (policy.approval_required[toolName]) {
        return { allowed: true, requiresApproval: true, reason: 'Tool requires approval' };
      }
    }

    return { allowed: true, requiresApproval: false };
  }

  async shutdown(): Promise<void> {
    await this.clientManager.disconnectAll();
    this.servers.clear();
    this.adapters.clear();
    this.healthRecords.clear();
  }
}

export function createMCPServerRegistry(options: MCPServerRegistryOptions): MCPServerRegistry {
  return new MCPServerRegistry(options);
}