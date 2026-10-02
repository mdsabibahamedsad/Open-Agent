import {
  ToolDefinition,
  ToolInvocation,
  ToolResult,
  ToolError,
  ToolErrorCode,
  ToolExecutionStatus,
  ToolExecutionRecord,
  ToolAdapter,
  ToolRateLimitConfig,
  ToolResourceLimits,
  CancellationToken,
  ValidationResult,
  JSONSchema,
} from './types';
import { ToolRegistry } from './registry';
import { PolicyEngine } from './policy';
import { RiskEngine } from './risk';
import { CredentialResolver } from './credentials';
import { SecretRedactor } from './secrets';
import { RateLimiter } from './rate-limiter';
import { OpenAgentLogger, createChildLogger } from '@openagent/logger';

const logger: OpenAgentLogger = createChildLogger({ module: 'tool-system:execution' });

export interface ToolExecutionOptions {
  default_timeout: number;
  max_retries: number;
  rate_limit: ToolRateLimitConfig;
  resource_limits: ToolResourceLimits;
  enable_artifacts: boolean;
  artifact_storage_url?: string;
}

export class ToolExecutionRuntime {
  private registry: ToolRegistry;
  private policyEngine: PolicyEngine;
  private riskEngine: RiskEngine;
  private credentialResolver: CredentialResolver;
  private secretRedactor: SecretRedactor;
  private rateLimiter: RateLimiter;
  private adapters: Map<string, ToolAdapter> = new Map();
  private executions: Map<string, ToolExecutionRecord> = new Map();
  private options: ToolExecutionOptions;

  constructor(
    registry: ToolRegistry,
    policyEngine: PolicyEngine,
    riskEngine: RiskEngine,
    credentialResolver: CredentialResolver,
    options: ToolExecutionOptions
  ) {
    this.registry = registry;
    this.policyEngine = policyEngine;
    this.riskEngine = riskEngine;
    this.credentialResolver = credentialResolver;
    this.secretRedactor = new SecretRedactor();
    this.rateLimiter = new RateLimiter(options.rate_limit);
    this.options = options;
  }

  registerAdapter(adapter: ToolAdapter): void {
    for (const toolType of adapter.supported_tool_types) {
      this.adapters.set(toolType, adapter);
    }
    logger.info('Tool adapter registered', { adapter_id: adapter.adapter_id, types: adapter.supported_tool_types });
  }

  async execute(invocation: ToolInvocation): Promise<ToolResult> {
    const executionId = invocation.execution_context.execution_id;
    const toolExecutionId = invocation.execution_context.tool_execution_id;
    const startTime = Date.now();

    logger.info('Tool execution started', {
      execution_id: executionId,
      tool_execution_id: toolExecutionId,
      tool_id: invocation.tool_id,
      tool_version: invocation.tool_version,
    });

    const executionRecord: ToolExecutionRecord = {
      id: toolExecutionId,
      tool_id: invocation.tool_id,
      tool_version_id: invocation.tool_version,
      organization_id: invocation.execution_context.organization_id,
      agent_id: invocation.execution_context.agent_id,
      workflow_id: invocation.execution_context.workflow_id,
      user_id: invocation.execution_context.user_id,
      status: 'QUEUED',
      input: invocation.input,
      started_at: new Date(),
      duration_ms: 0,
      retry_count: 0,
      metadata: {},
    };

    this.executions.set(toolExecutionId, executionRecord);

    try {
      const tool = await this.resolveTool(invocation.tool_id, invocation.tool_version);
      if (!tool) {
        return this.createErrorResult(
          invocation,
          'TOOL_NOT_FOUND',
          `Tool ${invocation.tool_id}@${invocation.tool_version} not found`,
          startTime
        );
      }

      executionRecord.status = 'RUNNING';

      await this.validateAuthorization(invocation, tool);
      await this.validatePolicy(invocation, tool);
      await this.validateRisk(invocation, tool);
      await this.validateInput(invocation, tool);

      const credentials = await this.resolveCredentials(invocation, tool);
      invocation.execution_context.credentials = credentials;

      await this.checkRateLimits(invocation);

      const adapter = this.getAdapter(tool);
      if (!adapter) {
        return this.createErrorResult(
          invocation,
          'TOOL_UNAVAILABLE',
          `No adapter found for tool type: ${tool.metadata.provider}`,
          startTime
        );
      }

      const timeout = invocation.timeout || tool.metadata.timeout || this.options.default_timeout;
      const result = await this.executeWithTimeout(adapter, invocation, timeout);

      await this.validateOutput(result, tool);

      const finalResult = this.secretRedactor.redactResult(result);
      this.recordExecution(finalResult, executionRecord, startTime);

      logger.info('Tool execution completed', {
        execution_id: executionId,
        tool_execution_id: toolExecutionId,
        status: finalResult.success ? 'success' : 'failed',
        duration_ms: finalResult.duration_ms,
      });

      return finalResult;
    } catch (error) {
      return this.handleExecutionError(invocation, error, executionRecord, startTime);
    }
  }

  async executeStreaming(
    invocation: ToolInvocation,
    onProgress: (event: { type: string; data: unknown }) => void
  ): Promise<ToolResult> {
    const tool = await this.resolveTool(invocation.tool_id, invocation.tool_version);
    if (!tool) {
      return this.execute(invocation);
    }
    const adapter = this.getAdapter(tool);
    if (!adapter || !('executeStreaming' in adapter)) {
      return this.execute(invocation);
    }

    return (adapter as any).executeStreaming(invocation.execution_context, invocation.input, onProgress);
  }

  async cancel(executionId: string): Promise<boolean> {
    const execution = this.executions.get(executionId);
    if (!execution) return false;

    if (execution.status === 'RUNNING' || execution.status === 'QUEUED' || execution.status === 'WAITING') {
      execution.status = 'CANCELLED';
      execution.completed_at = new Date();
      execution.duration_ms = Date.now() - execution.started_at.getTime();

      for (const adapter of this.adapters.values()) {
        if (typeof (adapter as any).cancel === 'function') {
          await (adapter as any).cancel(executionId);
        }
      }

      logger.info('Tool execution cancelled', { execution_id: executionId });
      return true;
    }

    return false;
  }

  getExecution(executionId: string): ToolExecutionRecord | undefined {
    return this.executions.get(executionId);
  }

  listExecutions(filters?: {
    tool_id?: string;
    organization_id?: string;
    agent_id?: string;
    workflow_id?: string;
    status?: ToolExecutionStatus;
    from?: Date;
    to?: Date;
  }): ToolExecutionRecord[] {
    let executions = Array.from(this.executions.values());

    if (filters) {
      if (filters.tool_id) executions = executions.filter(e => e.tool_id === filters.tool_id);
      if (filters.organization_id) executions = executions.filter(e => e.organization_id === filters.organization_id);
      if (filters.agent_id) executions = executions.filter(e => e.agent_id === filters.agent_id);
      if (filters.workflow_id) executions = executions.filter(e => e.workflow_id === filters.workflow_id);
      if (filters.status) executions = executions.filter(e => e.status === filters.status);
      if (filters.from) executions = executions.filter(e => e.started_at >= filters.from!);
      if (filters.to) executions = executions.filter(e => e.started_at <= filters.to!);
    }

    return executions.sort((a, b) => b.started_at.getTime() - a.started_at.getTime());
  }

  private async resolveTool(toolId: string, version: string): Promise<ToolDefinition | undefined> {
    let tool = this.registry.getById(toolId);
    if (!tool) {
      tool = this.registry.get(toolId, version);
    }
    return tool;
  }

  private getAdapter(tool: ToolDefinition): ToolAdapter | undefined {
    return this.adapters.get(tool.metadata.provider);
  }

  private async validateAuthorization(invocation: ToolInvocation, tool: ToolDefinition): Promise<void> {
    const { permissions } = invocation.execution_context;
    const requiredPermission = `tool:${tool.metadata.capabilities.join(':tool:')}`;

    if (!permissions.some(p => p === 'tool:execute' || p === requiredPermission || p === 'tool:manage')) {
      throw new ToolExecutionError('TOOL_NOT_AUTHORIZED', 'Insufficient permissions to execute tool', tool.id);
    }
  }

  private async validatePolicy(invocation: ToolInvocation, tool: ToolDefinition): Promise<void> {
    const allowed = await this.policyEngine.evaluate(
      tool,
      invocation.execution_context
    );

    if (!allowed.allowed) {
      if (allowed.requires_approval) {
        throw new ToolExecutionError('APPROVAL_REQUIRED', allowed.reason || 'Tool execution requires approval', tool.id);
      }
      throw new ToolExecutionError('TOOL_POLICY_BLOCKED', allowed.reason || 'Tool blocked by policy', tool.id);
    }
  }

  private async validateRisk(invocation: ToolInvocation, tool: ToolDefinition): Promise<void> {
    const riskResult = await this.riskEngine.evaluate(tool, invocation.execution_context);

    if (riskResult.blocked) {
      throw new ToolExecutionError('TOOL_POLICY_BLOCKED', riskResult.reason || 'Tool blocked by risk policy', tool.id);
    }

    if (riskResult.requires_approval) {
      throw new ToolExecutionError('APPROVAL_REQUIRED', riskResult.reason || 'High-risk tool requires approval', tool.id);
    }
  }

  private async validateInput(invocation: ToolInvocation, tool: ToolDefinition): Promise<void> {
    const adapter = this.getAdapter(tool);
    if (adapter) {
      const validation = await adapter.validate(tool, invocation.input);
      if (!validation.valid) {
        throw new ToolExecutionError(
          'INVALID_TOOL_INPUT',
          `Input validation failed: ${validation.errors.map(e => e.message).join(', ')}`,
          tool.id
        );
      }
    } else {
      const validation = this.validateSchema(invocation.input, tool.input_schema);
      if (!validation.valid) {
        throw new ToolExecutionError(
          'INVALID_TOOL_INPUT',
          `Input validation failed: ${validation.errors.map(e => e.message).join(', ')}`,
          tool.id
        );
      }
    }
  }

  private validateSchema(input: Record<string, unknown>, schema: JSONSchema): ValidationResult {
    const errors: { field: string; message: string; code: string }[] = [];

    const required = schema.required || [];
    for (const field of required) {
      if (!(field in input)) {
        errors.push({ field, message: `Required field '${field}' is missing`, code: 'REQUIRED_FIELD_MISSING' });
      }
    }

    const properties = schema.properties || {};
    for (const [field, value] of Object.entries(input)) {
      const propSchema = properties[field] as JSONSchema;
      if (propSchema) {
        const typeError = this.validateType(field, value, propSchema);
        if (typeError) errors.push(typeError);
      }
    }

    return { valid: errors.length === 0, errors };
  }

  private validateType(field: string, value: unknown, schema: JSONSchema): { field: string; message: string; code: string } | null {
    const expectedType = schema.type;
    if (!expectedType) return null;

    const typeMap: Record<string, (v: unknown) => boolean> = {
      string: (v) => typeof v === 'string',
      number: (v) => typeof v === 'number' && !isNaN(v),
      integer: (v) => Number.isInteger(v),
      boolean: (v) => typeof v === 'boolean',
      array: (v) => Array.isArray(v),
      object: (v) => typeof v === 'object' && v !== null && !Array.isArray(v),
    };

    const types = Array.isArray(expectedType) ? expectedType : [expectedType];
    for (const type of types) {
      const checker = typeMap[type];
      if (checker && !checker(value)) {
        return { field, message: `Field '${field}' must be of type ${type}`, code: 'TYPE_MISMATCH' };
      }
    }

    return null;
  }

  private async validateOutput(result: ToolResult, tool: ToolDefinition): Promise<void> {
    if (!tool.output_schema) return;

    if (result.output) {
      const validation = this.validateSchema(result.output, tool.output_schema);
      if (!validation.valid) {
        result.success = false;
        result.error = {
          code: 'TOOL_OUTPUT_INVALID',
          message: `Output validation failed: ${validation.errors.map(e => e.message).join(', ')}`,
          retryable: false,
        };
      }
    }
  }

  private async resolveCredentials(invocation: ToolInvocation, tool: ToolDefinition): Promise<Record<string, unknown>> {
    const credentialRefs = this.extractCredentialRefs(tool.configuration);
    return this.credentialResolver.resolve(credentialRefs, invocation.execution_context.organization_id);
  }

  private extractCredentialRefs(config: Record<string, unknown>): string[] {
    const refs: string[] = [];
    const traverse = (obj: unknown, path: string = '') => {
      if (typeof obj === 'object' && obj !== null) {
        for (const [key, value] of Object.entries(obj)) {
          const newPath = path ? `${path}.${key}` : key;
          if (key === 'credential_id' && typeof value === 'string') {
            refs.push(value);
          } else if (typeof value === 'object') {
            traverse(value, newPath);
          }
        }
      }
    };
    traverse(config);
    return refs;
  }

  private async checkRateLimits(invocation: ToolInvocation): Promise<void> {
    const { organization_id, user_id, agent_id } = invocation.execution_context;
    await this.rateLimiter.checkLimit(organization_id, user_id, agent_id);
  }

  private async executeWithTimeout(
    adapter: ToolAdapter,
    invocation: ToolInvocation,
    timeout: number
  ): Promise<ToolResult> {
    const startTime = Date.now();
    const deadline = new Date(startTime + timeout);
    invocation.execution_context.deadline = deadline;

    const cancellationToken = this.createCancellationToken(deadline);

    try {
      const result = await Promise.race([
        adapter.execute(invocation.execution_context, invocation.input),
        this.createTimeoutPromise(timeout),
      ]);

      const durationMs = Date.now() - startTime;

      return {
        ...result,
        duration_ms: durationMs,
        metadata: {
          ...result.metadata,
          adapter_id: adapter.adapter_id,
        },
      };
    } catch (error) {
      if (error instanceof ToolExecutionError) throw error;
      throw new ToolExecutionError('TOOL_EXECUTION_FAILED', String(error), invocation.tool_id);
    }
  }

  private createCancellationToken(deadline: Date): CancellationToken {
    let cancelled = false;
    let reason: string | undefined;
    const callbacks: (() => void)[] = [];

    const checkDeadline = () => {
      if (Date.now() >= deadline.getTime() && !cancelled) {
        cancelled = true;
        reason = 'timeout';
        callbacks.forEach(cb => cb());
      }
    };

    const interval = setInterval(checkDeadline, 100);

    return {
      get cancelled() {
        checkDeadline();
        return cancelled;
      },
      get reason() {
        return reason;
      },
      on_cancelled: (callback: () => void) => {
        callbacks.push(callback);
      },
    };
  }

  private createTimeoutPromise(timeout: number): Promise<never> {
    return new Promise((_, reject) => {
      setTimeout(() => reject(new ToolExecutionError('TOOL_TIMEOUT', `Execution timed out after ${timeout}ms`, '')), timeout);
    });
  }

  private createErrorResult(
    invocation: ToolInvocation,
    code: ToolErrorCode,
    message: string,
    startTime: number
  ): ToolResult {
    return {
      success: false,
      error: { code, message, retryable: this.isRetryableError(code) },
      metadata: {},
      duration_ms: Date.now() - startTime,
      retryable: this.isRetryableError(code),
      truncated: false,
      artifacts: [],
    };
  }

  private async handleExecutionError(
    invocation: ToolInvocation,
    error: unknown,
    executionRecord: ToolExecutionRecord,
    startTime: number
  ): Promise<ToolResult> {
    let toolError: ToolError;

    if (error instanceof ToolExecutionError) {
      toolError = {
        code: error.code,
        message: error.message,
        retryable: this.isRetryableError(error.code),
      };
    } else {
      toolError = {
        code: 'TOOL_EXECUTION_FAILED',
        message: String(error),
        retryable: false,
      };
    }

    executionRecord.status = 'FAILED';
    executionRecord.completed_at = new Date();
    executionRecord.duration_ms = Date.now() - startTime;
    executionRecord.error = toolError;

    logger.error('Tool execution failed', {
      execution_id: invocation.execution_context.execution_id,
      tool_execution_id: invocation.execution_context.tool_execution_id,
      tool_id: invocation.tool_id,
      error: toolError.message,
      code: toolError.code,
    });

    return {
      success: false,
      error: toolError,
      metadata: {},
      duration_ms: Date.now() - startTime,
      retryable: toolError.retryable,
      truncated: false,
      artifacts: [],
    };
  }

  private recordExecution(result: ToolResult, executionRecord: ToolExecutionRecord, startTime: number): void {
    executionRecord.status = result.success ? 'SUCCEEDED' : 'FAILED';
    executionRecord.completed_at = new Date();
    executionRecord.duration_ms = result.duration_ms;
    executionRecord.output = result.output;
    executionRecord.error = result.error;
    executionRecord.metadata = result.metadata;
  }

  private isRetryableError(code: ToolErrorCode): boolean {
    const retryableCodes: ToolErrorCode[] = [
      'TOOL_TIMEOUT',
      'TOOL_RATE_LIMITED',
      'TOOL_UNAVAILABLE',
      'PROVIDER_ERROR',
    ];
    return retryableCodes.includes(code);
  }
}

export class ToolExecutionError extends Error {
  public readonly code: ToolErrorCode;
  public readonly toolName: string;

  constructor(code: ToolErrorCode, message: string, toolName: string) {
    super(message);
    this.name = 'ToolExecutionError';
    this.code = code;
    this.toolName = toolName;
  }
}