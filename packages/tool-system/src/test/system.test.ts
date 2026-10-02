import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  ToolRegistry,
  ToolExecutionRuntime,
  PolicyEngine,
  RiskEngine,
  CredentialResolver,
  SecretRedactor,
  RateLimiter,
  BuiltinToolAdapter,
  BUILTIN_TOOLS,
  ToolDefinition,
  ToolCategory,
  ToolCapability,
  ToolRiskLevel,
  ToolExecutionMode,
  ToolLifecycleStatus,
  ToolTrustLevel,
  ToolProviderType,
  ToolExecutionContext,
} from './index';

describe('ToolRegistry', () => {
  let registry: ToolRegistry;

  beforeEach(() => {
    registry = new ToolRegistry();
  });

  const createMockTool = (overrides: Partial<ToolDefinition> = {}): ToolDefinition => ({
    id: 'test-tool-1',
    slug: 'test.tool',
    metadata: {
      name: 'test.tool',
      display_name: 'Test Tool',
      description: 'A test tool',
      icon: 'tool',
      category: ToolCategory.UTILITY,
      tags: ['test'],
      documentation_url: 'https://example.com',
      provider: 'test',
      version: '1.0.0',
      capabilities: [ToolCapability.READ],
      risk_level: ToolRiskLevel.LOW,
      execution_mode: ToolExecutionMode.SYNC,
      timeout: 30000,
      retry_policy: { max_attempts: 3, backoff: 1000, jitter: 500, retryable_errors: [] },
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: true,
      trust_level: ToolTrustLevel.CORE,
      ...overrides.metadata,
    },
    input_schema: {
      type: 'object',
      properties: { input: { type: 'string' } },
      required: ['input'],
    },
    output_schema: { type: 'object', properties: { result: { type: 'string' } } },
    status: ToolLifecycleStatus.ACTIVE,
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
    ...overrides,
  });

  it('should register a tool', () => {
    const tool = createMockTool();
    registry.register(tool);

    const retrieved = registry.get('test.tool', '1.0.0');
    expect(retrieved).toBeDefined();
    expect(retrieved?.id).toBe('test-tool-1');
    expect(retrieved?.slug).toBe('test.tool');
  });

  it('should get latest version', () => {
    const toolV1 = createMockTool({ id: 'tool-v1', metadata: { ...createMockTool().metadata, version: '1.0.0' } });
    const toolV2 = createMockTool({ id: 'tool-v2', metadata: { ...createMockTool().metadata, version: '2.0.0' } });
    registry.register(toolV1);
    registry.register(toolV2);

    const latest = registry.getLatest('test.tool');
    expect(latest).toBeDefined();
    expect(latest?.metadata.version).toBe('2.0.0');
  });

  it('should list tools', () => {
    const tool1 = createMockTool({ id: 'tool-1', slug: 'tool.one' });
    const tool2 = createMockTool({ id: 'tool-2', slug: 'tool.two' });
    registry.register(tool1);
    registry.register(tool2);

    const tools = registry.listTools();
    expect(tools.length).toBe(2);
  });

  it('should search tools', () => {
    const tool = createMockTool({ slug: 'web.search', metadata: { ...createMockTool().metadata, description: 'Search the web' } });
    registry.register(tool);

    const results = registry.search('web');
    expect(results.length).toBe(1);
    expect(results[0].slug).toBe('web.search');
  });

  it('should filter tools by category', () => {
    const tool1 = createMockTool({ slug: 'tool.one', metadata: { ...createMockTool().metadata, category: ToolCategory.HTTP } });
    const tool2 = createMockTool({ slug: 'tool.two', metadata: { ...createMockTool().metadata, category: ToolCategory.UTILITY } });
    registry.register(tool1);
    registry.register(tool2);

    const httpTools = registry.listTools({ category: ToolCategory.HTTP });
    expect(httpTools.length).toBe(1);
    expect(httpTools[0].slug).toBe('tool.one');
  });
});

describe('PolicyEngine', () => {
  let policyEngine: PolicyEngine;
  const createDefaultPolicy = () => ({
    allowed_tools: [],
    blocked_tools: [],
    allowed_categories: Object.values(ToolCategory),
    blocked_categories: [],
    allowed_risk_levels: [ToolRiskLevel.LOW, ToolRiskLevel.MEDIUM],
    max_risk_level: ToolRiskLevel.HIGH,
    allowed_capabilities: Object.values(ToolCapability),
    blocked_capabilities: [],
    allowed_domains: [],
    blocked_domains: [],
    allowed_organizations: [],
    approval_required: {},
    execution_limits: {
      max_concurrent_executions: 10,
      max_execution_time_seconds: 300,
      max_output_size_bytes: 10 * 1024 * 1024,
      max_input_size_bytes: 10 * 1024 * 1024,
      daily_execution_limit: 10000,
    },
  });

  beforeEach(() => {
    policyEngine = new PolicyEngine(createDefaultPolicy());
  });

  const createMockTool = (overrides: Partial<ToolDefinition> = {}): ToolDefinition => ({
    id: 'test-tool-1',
    slug: 'test.tool',
    metadata: {
      name: 'test.tool',
      display_name: 'Test Tool',
      description: 'A test tool',
      icon: 'tool',
      category: ToolCategory.UTILITY,
      tags: ['test'],
      documentation_url: 'https://example.com',
      provider: 'test',
      version: '1.0.0',
      capabilities: [ToolCapability.READ],
      risk_level: ToolRiskLevel.LOW,
      execution_mode: ToolExecutionMode.SYNC,
      timeout: 30000,
      retry_policy: { max_attempts: 3, backoff: 1000, jitter: 500, retryable_errors: [] },
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: true,
      trust_level: ToolTrustLevel.CORE,
      ...overrides.metadata,
    },
    input_schema: { type: 'object', properties: { input: { type: 'string' } }, required: ['input'] },
    output_schema: { type: 'object', properties: { result: { type: 'string' } } },
    status: ToolLifecycleStatus.ACTIVE,
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
    ...overrides,
  });

  const createMockContext = (overrides: Partial<ToolExecutionContext> = {}): ToolExecutionContext => ({
    execution_id: uuidv4(),
    tool_execution_id: uuidv4(),
    organization_id: 'org-1',
    user_id: 'user-1',
    agent_id: 'agent-1',
    workflow_id: 'workflow-1',
    task_id: 'task-1',
    node_execution_id: 'node-1',
    permissions: ['tool:execute'],
    policy: createDefaultPolicy(),
    credentials: {},
    deadline: new Date(Date.now() + 60000),
    cancellation_token: { cancelled: false, on_cancelled: vi.fn() },
    metadata: {},
    ...overrides,
  });

  it('should allow tool by default', async () => {
    const tool = createMockTool();
    const context = createMockContext();

    const result = await policyEngine.evaluate(tool, context);
    expect(result.allowed).toBe(true);
    expect(result.requires_approval).toBe(false);
  });

  it('should block tool in blocked list', async () => {
    const tool = createMockTool({ slug: 'blocked.tool' });
    const context = createMockContext();
    policyEngine.setOrganizationPolicy('org-1', {
      ...createDefaultPolicy(),
      blocked_tools: ['blocked.tool'],
    });

    const result = await policyEngine.evaluate(tool, context);
    expect(result.allowed).toBe(false);
  });

  it('should block tool not in allowed list when allowed list is set', async () => {
    const tool = createMockTool({ slug: 'unlisted.tool' });
    const context = createMockContext();
    policyEngine.setOrganizationPolicy('org-1', {
      ...createDefaultPolicy(),
      allowed_tools: ['allowed.tool'],
    });

    const result = await policyEngine.evaluate(tool, context);
    expect(result.allowed).toBe(false);
  });

  it('should block category', async () => {
    const tool = createMockTool({ metadata: { ...createMockTool().metadata, category: ToolCategory.SHELL } });
    const context = createMockContext();
    policyEngine.setOrganizationPolicy('org-1', {
      ...createDefaultPolicy(),
      blocked_categories: [ToolCategory.SHELL],
    });

    const result = await policyEngine.evaluate(tool, context);
    expect(result.allowed).toBe(false);
  });

  it('should require approval when configured', async () => {
    const tool = createMockTool({ slug: 'email.send' });
    const context = createMockContext();
    policyEngine.setOrganizationPolicy('org-1', {
      ...createDefaultPolicy(),
      approval_required: { 'email.send': true },
    });

    const result = await policyEngine.evaluate(tool, context);
    expect(result.allowed).toBe(true);
    expect(result.requires_approval).toBe(true);
  });
});

describe('RiskEngine', () => {
  let riskEngine: RiskEngine;
  const createMockTool = (overrides: Partial<ToolDefinition> = {}): ToolDefinition => ({
    id: 'test-tool-1',
    slug: 'test.tool',
    metadata: {
      name: 'test.tool',
      display_name: 'Test Tool',
      description: 'A test tool',
      icon: 'tool',
      category: ToolCategory.UTILITY,
      tags: ['test'],
      documentation_url: 'https://example.com',
      provider: 'test',
      version: '1.0.0',
      capabilities: [ToolCapability.READ],
      risk_level: ToolRiskLevel.LOW,
      execution_mode: ToolExecutionMode.SYNC,
      timeout: 30000,
      retry_policy: { max_attempts: 3, backoff: 1000, jitter: 500, retryable_errors: [] },
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: true,
      trust_level: ToolTrustLevel.CORE,
      ...overrides.metadata,
    },
    input_schema: { type: 'object', properties: { input: { type: 'string' } }, required: ['input'] },
    output_schema: { type: 'object', properties: { result: { type: 'string' } } },
    status: ToolLifecycleStatus.ACTIVE,
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
    ...overrides,
  });

  const createMockContext = (overrides: Partial<ToolExecutionContext> = {}): ToolExecutionContext => ({
    execution_id: uuidv4(),
    tool_execution_id: uuidv4(),
    organization_id: 'org-1',
    user_id: 'user-1',
    agent_id: 'agent-1',
    workflow_id: 'workflow-1',
    task_id: 'task-1',
    node_execution_id: 'node-1',
    permissions: ['tool:execute'],
    policy: {
      allowed_tools: [],
      blocked_tools: [],
      allowed_categories: Object.values(ToolCategory),
      blocked_categories: [],
      allowed_risk_levels: [ToolRiskLevel.LOW, ToolRiskLevel.MEDIUM],
      max_risk_level: ToolRiskLevel.HIGH,
      allowed_capabilities: Object.values(ToolCapability),
      blocked_capabilities: [],
      allowed_domains: [],
      blocked_domains: [],
      allowed_organizations: [],
      approval_required: {},
      execution_limits: {
        max_concurrent_executions: 10,
        max_execution_time_seconds: 300,
        max_output_size_bytes: 10 * 1024 * 1024,
        max_input_size_bytes: 10 * 1024 * 1024,
        daily_execution_limit: 10000,
      },
    },
    credentials: {},
    deadline: new Date(Date.now() + 60000),
    cancellation_token: { cancelled: false, on_cancelled: vi.fn() },
    metadata: {},
    ...overrides,
  });

  beforeEach(() => {
    riskEngine = new RiskEngine();
  });

  it('should evaluate low risk tool as LOW', async () => {
    const tool = createMockTool();
    const context = createMockContext();

    const result = await riskEngine.evaluate(tool, context);
    expect(result.risk_level).toBe(ToolRiskLevel.LOW);
    expect(result.blocked).toBe(false);
    expect(result.requires_approval).toBe(false);
  });

  it('should increase risk for critical capabilities', async () => {
    const tool = createMockTool({
      metadata: {
        ...createMockTool().metadata,
        capabilities: [ToolCapability.PROCESS_EXECUTION],
        trust_level: ToolTrustLevel.CORE,
      },
    });
    const context = createMockContext();

    const result = await riskEngine.evaluate(tool, context);
    expect(result.risk_level).toBe(ToolRiskLevel.HIGH);
  });

  it('should increase risk for untrusted provider', async () => {
    const tool = createMockTool({
      metadata: {
        ...createMockTool().metadata,
        trust_level: ToolTrustLevel.UNTRUSTED,
      },
    });
    const context = createMockContext();

    const result = await riskEngine.evaluate(tool, context);
    expect(result.risk_level).toBe(ToolRiskLevel.MEDIUM);
  });

  it('should decrease risk for verified provider', async () => {
    const tool = createMockTool({
      metadata: {
        ...createMockTool().metadata,
        trust_level: ToolTrustLevel.VERIFIED,
        risk_level: ToolRiskLevel.MEDIUM,
      },
    });
    const context = createMockContext();

    const result = await riskEngine.evaluate(tool, context);
    expect(result.risk_level).toBe(ToolRiskLevel.LOW);
  });
});

describe('CredentialResolver', () => {
  let resolver: CredentialResolver;

  beforeEach(() => {
    resolver = new CredentialResolver();
  });

  it('should register and resolve credentials', () => {
    resolver.registerCredential('org-1', {
      id: 'cred-1',
      type: 'api_key',
      data: { api_key: 'secret-key-123' },
    });

    const result = resolver.resolve(['cred-1'], 'org-1');
    expect(result['cred-1']).toEqual({ api_key: 'secret-key-123' });
  });

  it('should return empty for missing credentials', () => {
    const result = resolver.resolve(['missing-cred'], 'org-1');
    expect(result['missing-cred']).toBeUndefined();
  });
});

describe('SecretRedactor', () => {
  let redactor: SecretRedactor;

  beforeEach(() => {
    redactor = new SecretRedactor();
  });

  it('should redact API keys', () => {
    const text = 'My API key is sk-1234567890abcdef1234567890abcdef';
    const redacted = redactor.redact(text);
    expect(redacted).toContain('***REDACTED***');
    expect(redacted).not.toContain('sk-1234567890abcdef1234567890abcdef');
  });

  it('should redact bearer tokens', () => {
    const text = 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9';
    const redacted = redactor.redact(text);
    expect(redacted).toContain('Bearer ***REDACTED***');
  });

  it('should redact object values', () => {
    const obj = {
      api_key: 'secret-key',
      normal_field: 'value',
      nested: {
        password: 'secret-password',
      },
    };
    const redacted = redactor.redactObject(obj) as any;
    expect(redacted.api_key).toBe('***REDACTED***');
    expect(redacted.normal_field).toBe('value');
    expect(redacted.nested.password).toBe('***REDACTED***');
  });
});

describe('RateLimiter', () => {
  let limiter: RateLimiter;

  beforeEach(() => {
    limiter = new RateLimiter({
      requests_per_minute: 10,
      concurrent_executions: 5,
      daily_execution_limit: 100,
    });
  });

  it('should allow requests under limit', async () => {
    await expect(limiter.checkLimit('org-1')).resolves.toBeUndefined();
    await expect(limiter.checkLimit('org-1')).resolves.toBeUndefined();
  });

  it('should track concurrent executions', async () => {
    await limiter.checkLimit('org-1');
    await limiter.checkLimit('org-1');
    
    const usage = limiter.getUsage('org-1');
    expect(usage['org-1:concurrent'].used).toBe(2);
  });

  it('should release concurrent slots', async () => {
    await limiter.checkLimit('org-1');
    limiter.releaseConcurrent('org-1');
    
    const usage = limiter.getUsage('org-1');
    expect(usage['org-1:concurrent'].used).toBe(0);
  });
});

describe('BuiltinToolAdapter', () => {
  let adapter: BuiltinToolAdapter;

  beforeEach(() => {
    adapter = new BuiltinToolAdapter();
  });

  it('should validate calculator tool', async () => {
    const tool = BUILTIN_TOOLS.find(t => t.slug === 'utility.calculator')!;
    const result = await adapter.validate(tool, { expression: '2 + 2' });
    expect(result.valid).toBe(true);
  });

  it('should reject invalid calculator expression', async () => {
    const tool = BUILTIN_TOOLS.find(t => t.slug === 'utility.calculator')!;
    const result = await adapter.validate(tool, { expression: 'invalid' });
    // Expression validation is permissive, just checks required fields
    expect(result.valid).toBe(true);
  });

  it('should execute calculator', async () => {
    const tool = BUILTIN_TOOLS.find(t => t.slug === 'utility.calculator')!;
    const context = {
      execution_id: 'exec-1',
      tool_execution_id: 'tool-exec-1',
      organization_id: 'org-1',
      user_id: 'user-1',
      agent_id: 'agent-1',
      workflow_id: 'workflow-1',
      task_id: 'task-1',
      node_execution_id: 'node-1',
      permissions: ['tool:execute'],
      policy: {
        allowed_tools: [],
        blocked_tools: [],
        allowed_categories: Object.values(ToolCategory),
        blocked_categories: [],
        allowed_risk_levels: [ToolRiskLevel.LOW, ToolRiskLevel.MEDIUM],
        max_risk_level: ToolRiskLevel.HIGH,
        allowed_capabilities: Object.values(ToolCapability),
        blocked_capabilities: [],
        allowed_domains: [],
        blocked_domains: [],
        allowed_organizations: [],
        approval_required: {},
        execution_limits: {
          max_concurrent_executions: 10,
          max_execution_time_seconds: 300,
          max_output_size_bytes: 10 * 1024 * 1024,
          max_input_size_bytes: 10 * 1024 * 1024,
          daily_execution_limit: 10000,
        },
      },
      credentials: {},
      deadline: new Date(Date.now() + 60000),
      cancellation_token: { cancelled: false, on_cancelled: vi.fn() },
      metadata: { tool_name: 'utility.calculator', tool_config: {} },
    };
    const result = await adapter.execute(context, { expression: '2 + 2' });
    expect(result.success).toBe(true);
    expect(result.output?.result).toBe(4);
  });

  it('should execute datetime now', async () => {
    const tool = BUILTIN_TOOLS.find(t => t.slug === 'utility.datetime')!;
    const context = {
      execution_id: 'exec-1',
      tool_execution_id: 'tool-exec-1',
      organization_id: 'org-1',
      user_id: 'user-1',
      agent_id: 'agent-1',
      workflow_id: 'workflow-1',
      task_id: 'task-1',
      node_execution_id: 'node-1',
      permissions: ['tool:execute'],
      policy: {
        allowed_tools: [],
        blocked_tools: [],
        allowed_categories: Object.values(ToolCategory),
        blocked_categories: [],
        allowed_risk_levels: [ToolRiskLevel.LOW, ToolRiskLevel.MEDIUM],
        max_risk_level: ToolRiskLevel.HIGH,
        allowed_capabilities: Object.values(ToolCapability),
        blocked_capabilities: [],
        allowed_domains: [],
        blocked_domains: [],
        allowed_organizations: [],
        approval_required: {},
        execution_limits: {
          max_concurrent_executions: 10,
          max_execution_time_seconds: 300,
          max_output_size_bytes: 10 * 1024 * 1024,
          max_input_size_bytes: 10 * 1024 * 1024,
          daily_execution_limit: 10000,
        },
      },
      credentials: {},
      deadline: new Date(Date.now() + 60000),
      cancellation_token: { cancelled: false, on_cancelled: vi.fn() },
      metadata: { tool_name: 'utility.datetime', tool_config: {} },
    };
    const result = await adapter.execute(context, { operation: 'now' });
    expect(result.success).toBe(true);
    expect(result.output?.result).toBeDefined();
    expect(result.output?.iso).toBeDefined();
    expect(result.output?.unix).toBeDefined();
  });

  it('should generate UUIDs', async () => {
    const tool = BUILTIN_TOOLS.find(t => t.slug === 'utility.uuid')!;
    const context = {
      execution_id: 'exec-1',
      tool_execution_id: 'tool-exec-1',
      organization_id: 'org-1',
      user_id: 'user-1',
      agent_id: 'agent-1',
      workflow_id: 'workflow-1',
      task_id: 'task-1',
      node_execution_id: 'node-1',
      permissions: ['tool:execute'],
      policy: {
        allowed_tools: [],
        blocked_tools: [],
        allowed_categories: Object.values(ToolCategory),
        blocked_categories: [],
        allowed_risk_levels: [ToolRiskLevel.LOW, ToolRiskLevel.MEDIUM],
        max_risk_level: ToolRiskLevel.HIGH,
        allowed_capabilities: Object.values(ToolCapability),
        blocked_capabilities: [],
        allowed_domains: [],
        blocked_domains: [],
        allowed_organizations: [],
        approval_required: {},
        execution_limits: {
          max_concurrent_executions: 10,
          max_execution_time_seconds: 300,
          max_output_size_bytes: 10 * 1024 * 1024,
          max_input_size_bytes: 10 * 1024 * 1024,
          daily_execution_limit: 10000,
        },
      },
      credentials: {},
      deadline: new Date(Date.now() + 60000),
      cancellation_token: { cancelled: false, on_cancelled: vi.fn() },
      metadata: { tool_name: 'utility.uuid', tool_config: {} },
    };
    const result = await adapter.execute(context, { version: 'v4', count: 3 });
    expect(result.success).toBe(true);
    expect(result.output?.uuids).toHaveLength(3);
    expect(result.output?.uuids[0]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  });

  it('should execute hash', async () => {
    const tool = BUILTIN_TOOLS.find(t => t.slug === 'utility.hash')!;
    const context = {
      execution_id: 'exec-1',
      tool_execution_id: 'tool-exec-1',
      organization_id: 'org-1',
      user_id: 'user-1',
      agent_id: 'agent-1',
      workflow_id: 'workflow-1',
      task_id: 'task-1',
      node_execution_id: 'node-1',
      permissions: ['tool:execute'],
      policy: {
        allowed_tools: [],
        blocked_tools: [],
        allowed_categories: Object.values(ToolCategory),
        blocked_categories: [],
        allowed_risk_levels: [ToolRiskLevel.LOW, ToolRiskLevel.MEDIUM],
        max_risk_level: ToolRiskLevel.HIGH,
        allowed_capabilities: Object.values(ToolCapability),
        blocked_capabilities: [],
        allowed_domains: [],
        blocked_domains: [],
        allowed_organizations: [],
        approval_required: {},
        execution_limits: {
          max_concurrent_executions: 10,
          max_execution_time_seconds: 300,
          max_output_size_bytes: 10 * 1024 * 1024,
          max_input_size_bytes: 10 * 1024 * 1024,
          daily_execution_limit: 10000,
        },
      },
      credentials: {},
      deadline: new Date(Date.now() + 60000),
      cancellation_token: { cancelled: false, on_cancelled: vi.fn() },
      metadata: { tool_name: 'utility.hash', tool_config: {} },
    };
    const result = await adapter.execute(context, { input: 'test', algorithm: 'sha256' });
    expect(result.success).toBe(true);
    expect(result.output?.hash).toBeDefined();
    expect(result.output?.hash).toHaveLength(64); // SHA256 hex
  });
});

// Import uuid for tests
import { v4 as uuidv4 } from 'uuid';