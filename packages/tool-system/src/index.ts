export * from './types';
export * from './registry';
export * from './execution';
export * from './policy';
export * from './risk';
export * from './credentials';
export * from './secrets';
export * from './rate-limiter';
export * from './builtins';
export * from './integrations';

import { ToolRegistry } from './registry';
import { ToolExecutionRuntime, ToolExecutionOptions } from './execution';
import { PolicyEngine, createDefaultGlobalPolicy } from './policy';
import { RiskEngine } from './risk';
import { CredentialResolver, CredentialManager } from './credentials';
import { SecretRedactor, createSecretRedactor } from './secrets';
import { RateLimiter, createRateLimiter } from './rate-limiter';
import { BuiltinToolAdapter, BUILTIN_TOOLS, createBuiltinAdapter } from './builtins';
import {
  MCPIntegration,
  BrowserIntegration,
  CodingIntegration,
  MarketplaceIntegration,
  createMCPIntegration,
  createBrowserIntegration,
  createCodingIntegration,
  createMarketplaceIntegration,
} from './integrations';

export interface ToolSystemConfig {
  execution: ToolExecutionOptions;
  globalPolicy?: ReturnType<typeof createDefaultGlobalPolicy>;
}

export class ToolSystem {
  public readonly registry: ToolRegistry;
  public readonly policyEngine: PolicyEngine;
  public readonly riskEngine: RiskEngine;
  public readonly credentialResolver: CredentialResolver;
  public readonly credentialManager: CredentialManager;
  public readonly secretRedactor: SecretRedactor;
  public readonly rateLimiter: RateLimiter;
  public readonly executionRuntime: ToolExecutionRuntime;
  public readonly builtinAdapter: BuiltinToolAdapter;
  public readonly mcpIntegration: MCPIntegration;
  public readonly browserIntegration: BrowserIntegration;
  public readonly codingIntegration: CodingIntegration;
  public readonly marketplaceIntegration: MarketplaceIntegration;

  constructor(config: ToolSystemConfig) {
    this.registry = new ToolRegistry();
    this.policyEngine = new PolicyEngine(config.globalPolicy || createDefaultGlobalPolicy());
    this.riskEngine = new RiskEngine();
    this.credentialResolver = new CredentialResolver();
    this.credentialManager = new CredentialManager(this.credentialResolver);
    this.secretRedactor = createSecretRedactor();
    this.rateLimiter = createRateLimiter(config.execution.rate_limit);

    this.executionRuntime = new ToolExecutionRuntime(
      this.registry,
      this.policyEngine,
      this.riskEngine,
      this.credentialResolver,
      config.execution
    );

    this.builtinAdapter = createBuiltinAdapter();
    this.executionRuntime.registerAdapter(this.builtinAdapter);

    this.mcpIntegration = createMCPIntegration(this.registry, this.executionRuntime);
    this.browserIntegration = createBrowserIntegration(this.registry);
    this.codingIntegration = createCodingIntegration(this.registry);
    this.marketplaceIntegration = createMarketplaceIntegration(this.registry);

    this.registerBuiltinTools();
  }

  private registerBuiltinTools(): void {
    for (const tool of BUILTIN_TOOLS) {
      this.registry.register(tool);
    }
  }

  async shutdown(): Promise<void> {
    this.rateLimiter.shutdown();
  }
}

export function createToolSystem(config: ToolSystemConfig): ToolSystem {
  return new ToolSystem(config);
}

export const defaultExecutionOptions: ToolExecutionOptions = {
  default_timeout: 30000,
  max_retries: 2,
  rate_limit: {
    requests_per_minute: 60,
    concurrent_executions: 10,
    daily_execution_limit: 10000,
    organization_quota: 100000,
    agent_quota: 1000,
    user_quota: 5000,
  },
  resource_limits: {
    execution_timeout_ms: 300000,
    memory_limit_mb: 512,
    output_size_limit_bytes: 10 * 1024 * 1024,
    input_size_limit_bytes: 10 * 1024 * 1024,
    max_network_requests: 100,
    max_subprocesses: 0,
    max_concurrency: 10,
  },
  enable_artifacts: true,
};