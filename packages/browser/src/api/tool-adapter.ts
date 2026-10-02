import {
  ToolDefinition,
  ToolResult,
  ToolExecutionContext,
  ToolAdapter,
  ValidationResult,
  ToolErrorCode,
} from '@openagent/tool-system';
import {
  BrowserActionType,
  BrowserAction,
  BrowserObservation,
} from '../core/types';
import { browserSessionManager } from '../session/manager';
import { browserTaskManager } from '../tasks/manager';
import { domExtractor } from '../extraction/dom';
import { actionExecutorRegistry, actionValidator, ActionContext } from '../actions/executors';
import { createChildLogger } from '@openagent/logger';

const logger = createChildLogger({ module: 'browser:tool-adapter' });

export interface BrowserToolAdapterConfig {
  defaultTimeout: number;
  maxRetries: number;
  enableObservations: boolean;
  observationStrategy: 'minimal' | 'standard' | 'detailed' | 'visual';
}

export class BrowserToolAdapter implements ToolAdapter {
  readonly adapter_id = 'browser';
  readonly supported_tool_types = ['browser'];
  private config: BrowserToolAdapterConfig;

  constructor(config: Partial<BrowserToolAdapterConfig> = {}) {
    this.config = {
      defaultTimeout: 60000,
      maxRetries: 2,
      enableObservations: true,
      observationStrategy: 'standard',
      ...config,
    };
  }

  async validate(tool: ToolDefinition, input: Record<string, unknown>): Promise<ValidationResult> {
    const actionType = this.getActionTypeFromTool(tool);
    if (!actionType) {
      return { valid: false, errors: [{ field: 'tool', message: 'Unknown browser tool', code: 'UNKNOWN_TOOL' }] };
    }

    const mockAction: BrowserAction = {
      id: 'validation',
      taskId: 'validation',
      sessionId: 'validation',
      pageId: 'validation',
      type: actionType,
      input,
      riskLevel: 'MEDIUM',
      status: 'PENDING',
      retryCount: 0,
    };

    const context: ActionContext = {
      sessionId: input.sessionId as string || '',
      pageId: input.pageId as string || '',
      organizationId: 'validation',
    };

    const validation = actionValidator.validate(mockAction, context);
    return {
      valid: validation.valid,
      errors: validation.errors.map(e => ({ field: 'input', message: e, code: 'VALIDATION_ERROR' })),
    };
  }

  async execute(context: ToolExecutionContext, input: Record<string, unknown>): Promise<ToolResult> {
    const startTime = Date.now();
    
    try {
      const tool = context.metadata.tool as ToolDefinition;
      const actionType = this.getActionTypeFromTool(tool);
      
      if (!actionType) {
        return this.createErrorResult('TOOL_NOT_FOUND', `Unknown browser tool: ${tool.slug}`, startTime);
      }

      // Get session
      const sessionId = input.sessionId as string;
      if (!sessionId) {
        return this.createErrorResult('INVALID_TOOL_INPUT', 'sessionId is required', startTime);
      }

      const session = await browserSessionManager.getSessionInternal(sessionId);
      if (!session) {
        return this.createErrorResult('TOOL_NOT_FOUND', `Session ${sessionId} not found`, startTime);
      }

      // Get page
      const pageId = input.pageId as string || Array.from(session.pages.keys())[0];
      if (!pageId) {
        return this.createErrorResult('INVALID_TOOL_INPUT', 'No active page in session', startTime);
      }

      const page = session.pages.get(pageId);
      if (!page) {
        return this.createErrorResult('TOOL_NOT_FOUND', `Page ${pageId} not found`, startTime);
      }

      // Create action
      const action: BrowserAction = {
        id: `action_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        taskId: input.taskId as string || 'unknown',
        sessionId,
        pageId,
        type: actionType,
        input,
        riskLevel: actionValidator.getRiskLevel(actionType),
        status: 'RUNNING',
        startedAt: new Date(),
        retryCount: 0,
      };

      // Validate action
      const actionContext: ActionContext = {
        sessionId,
        pageId,
        organizationId: context.organization_id,
        agentId: context.agent_id,
        taskId: context.task_id,
      };

      const validation = actionValidator.validate(action, actionContext);
      if (!validation.valid) {
        return this.createErrorResult('INVALID_TOOL_INPUT', validation.errors.join(', '), startTime);
      }

      // Check approval requirement
      if (validation.requiresApproval && !input.approved) {
        return {
          success: false,
          error: {
            code: 'APPROVAL_REQUIRED',
            message: `Action ${actionType} requires approval`,
            retryable: false,
          },
          metadata: { requiresApproval: true, actionType },
          duration_ms: Date.now() - startTime,
          retryable: false,
          truncated: false,
          artifacts: [],
        };
      }

      // Execute action
      const result = await actionExecutorRegistry.execute(action, page);
      
      // Update activity
      await browserSessionManager.updateActivity(sessionId);

      // Get observation if enabled
      let observation: BrowserObservation | undefined;
      if (this.config.enableObservations && result.success) {
        observation = await domExtractor.extractObservation(page, undefined, this.config.observationStrategy);
      }

      // Record in task if taskId provided
      if (context.task_id) {
        await browserTaskManager.addAction(context.task_id, action);
        await browserTaskManager.updateActionResult(context.task_id, action.id, result);
        if (observation) {
          await browserTaskManager.addObservation(context.task_id, observation);
        }
      }

      return {
        success: result.success,
        output: {
          ...result.output,
          observation: observation ? this.serializeObservation(observation) : undefined,
          actionId: action.id,
        },
        error: result.error ? {
          code: 'TOOL_EXECUTION_FAILED' as const,
          message: result.error.message,
          retryable: result.error.retryable,
        } : undefined,
        metadata: {
          adapter_id: this.adapter_id,
          actionType,
          sessionId,
          pageId,
        },
        duration_ms: Date.now() - startTime,
        retryable: result.error?.retryable ?? false,
        truncated: false,
        artifacts: result.artifacts?.map(a => ({
          id: a.artifactId,
          type: a.type,
          name: a.name,
          size: a.size,
          url: a.storageRef,
          metadata: a.metadata ?? {},
        })) || [],
      };
    } catch (error) {
      logger.error('Browser tool execution failed', { error: String(error) });
      return this.createErrorResult('TOOL_EXECUTION_FAILED', String(error), startTime);
    }
  }

  async cancel(executionId: string): Promise<void> {
    // Would need to track running executions
    logger.info('Browser tool cancellation requested', { executionId });
  }

  private getActionTypeFromTool(tool: ToolDefinition): BrowserActionType | null {
    const slug = tool.slug;
    if (slug.startsWith('browser.')) {
      const actionPart = slug.replace('browser.', '').toUpperCase();
      return actionPart as BrowserActionType;
    }
    return null;
  }

  private createErrorResult(code: ToolErrorCode, message: string, startTime: number): ToolResult {
    return {
      success: false,
      error: { code, message, retryable: this.isRetryableError(code) },
      metadata: { adapter_id: this.adapter_id },
      duration_ms: Date.now() - startTime,
      retryable: this.isRetryableError(code),
      truncated: false,
      artifacts: [],
    };
  }

  private isRetryableError(code: ToolErrorCode): boolean {
    return ['TOOL_TIMEOUT', 'TOOL_RATE_LIMITED', 'TOOL_UNAVAILABLE', 'PROVIDER_ERROR'].includes(code);
  }

  private serializeObservation(observation: BrowserObservation): Record<string, unknown> {
    return {
      url: observation.url,
      title: observation.title,
      viewport: observation.viewport,
      scrollPosition: observation.scrollPosition,
      interactiveElements: observation.interactiveElements.map(el => ({
        id: el.id,
        role: el.role,
        name: el.name,
        visible: el.visible,
        enabled: el.enabled,
        boundingBox: el.boundingBox,
      })),
      textContent: observation.textContent,
      metadata: observation.metadata,
    };
  }
}

export function createBrowserToolAdapter(config?: Partial<BrowserToolAdapterConfig>): BrowserToolAdapter {
  return new BrowserToolAdapter(config);
}

export const BROWSER_TOOL_DEFINITIONS: ToolDefinition[] = [
  {
    id: 'browser.open',
    organization_id: undefined,
    slug: 'browser.open',
    metadata: {
      name: 'browser.open',
      display_name: 'Browser Open',
      description: 'Navigate to a URL in the browser',
      icon: 'globe',
      category: 'browser',
      tags: ['browser', 'navigate', 'web'],
      documentation_url: 'https://docs.openagent.ai/tools/browser-open',
      provider: 'browser',
      version: '1.0.0',
      capabilities: ['network', 'browser_control', 'read'],
      risk_level: 'MEDIUM',
      execution_mode: 'SYNC',
      timeout: 60000,
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: false,
      trust_level: 'ORGANIZATION',
    },
    input_schema: {
      type: 'object',
      properties: {
        sessionId: { type: 'string', description: 'Browser session ID' },
        url: { type: 'string', format: 'uri', description: 'URL to navigate to' },
        waitUntil: { type: 'string', enum: ['load', 'domcontentloaded', 'networkidle', 'commit'], default: 'networkidle' },
        timeout: { type: 'number', default: 30000 },
      },
      required: ['sessionId', 'url'],
    },
    output_schema: {
      type: 'object',
      properties: {
        url: { type: 'string' },
        title: { type: 'string' },
        status: { type: 'number' },
        loadTime: { type: 'number' },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.click',
    organization_id: undefined,
    slug: 'browser.click',
    metadata: {
      name: 'browser.click',
      display_name: 'Browser Click',
      description: 'Click an element on the page',
      icon: 'mouse-pointer',
      category: 'browser',
      tags: ['browser', 'click', 'interact'],
      provider: 'browser',
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
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
        selector: { type: 'string', description: 'CSS selector or element criteria' },
        button: { type: 'string', enum: ['left', 'right', 'middle'], default: 'left' },
        clickCount: { type: 'number', default: 1 },
        coordinates: { type: 'object', properties: { x: { type: 'number' }, y: { type: 'number' } } },
        force: { type: 'boolean', default: false },
      },
      required: ['sessionId', 'selector'],
    },
    output_schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.type',
    organization_id: undefined,
    slug: 'browser.type',
    metadata: {
      name: 'browser.type',
      display_name: 'Browser Type',
      description: 'Type text into an element',
      icon: 'keyboard',
      category: 'browser',
      tags: ['browser', 'type', 'input'],
      provider: 'browser',
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
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
        selector: { type: 'string' },
        text: { type: 'string' },
        delay: { type: 'number', default: 0 },
      },
      required: ['sessionId', 'selector', 'text'],
    },
    output_schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.fill',
    organization_id: undefined,
    slug: 'browser.fill',
    metadata: {
      name: 'browser.fill',
      display_name: 'Browser Fill',
      description: 'Fill a form field',
      icon: 'edit',
      category: 'browser',
      tags: ['browser', 'fill', 'form'],
      provider: 'browser',
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
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
        selector: { type: 'string' },
        value: { type: 'string' },
        force: { type: 'boolean', default: false },
      },
      required: ['sessionId', 'selector', 'value'],
    },
    output_schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.select',
    organization_id: undefined,
    slug: 'browser.select',
    metadata: {
      name: 'browser.select',
      display_name: 'Browser Select',
      description: 'Select an option from a dropdown',
      icon: 'chevron-down',
      category: 'browser',
      tags: ['browser', 'select', 'dropdown'],
      provider: 'browser',
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
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
        selector: { type: 'string' },
        value: { type: 'string' },
      },
      required: ['sessionId', 'selector', 'value'],
    },
    output_schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        selectedValues: { type: 'array', items: { type: 'string' } },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.hover',
    organization_id: undefined,
    slug: 'browser.hover',
    metadata: {
      name: 'browser.hover',
      display_name: 'Browser Hover',
      description: 'Hover over an element',
      icon: 'cursor',
      category: 'browser',
      tags: ['browser', 'hover'],
      provider: 'browser',
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
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
        selector: { type: 'string' },
      },
      required: ['sessionId', 'selector'],
    },
    output_schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.scroll',
    organization_id: undefined,
    slug: 'browser.scroll',
    metadata: {
      name: 'browser.scroll',
      display_name: 'Browser Scroll',
      description: 'Scroll the page',
      icon: 'arrows-up-down',
      category: 'browser',
      tags: ['browser', 'scroll'],
      provider: 'browser',
      version: '1.0.0',
      capabilities: ['browser_control', 'read'],
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
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
        x: { type: 'number' },
        y: { type: 'number' },
        selector: { type: 'string', description: 'Scroll element into view' },
      },
    },
    output_schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        scrollPosition: { type: 'object', properties: { x: { type: 'number' }, y: { type: 'number' } } },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.wait',
    organization_id: undefined,
    slug: 'browser.wait',
    metadata: {
      name: 'browser.wait',
      display_name: 'Browser Wait',
      description: 'Wait for a condition',
      icon: 'clock',
      category: 'browser',
      tags: ['browser', 'wait'],
      provider: 'browser',
      version: '1.0.0',
      capabilities: ['browser_control', 'read'],
      risk_level: 'LOW',
      execution_mode: 'SYNC',
      timeout: 60000,
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: true,
      trust_level: 'ORGANIZATION',
    },
    input_schema: {
      type: 'object',
      properties: {
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
        selector: { type: 'string' },
        state: { type: 'string', enum: ['attached', 'detached', 'visible', 'hidden'], default: 'visible' },
        timeout: { type: 'number', default: 30000 },
        function: { type: 'string', description: 'JavaScript function to wait for' },
      },
    },
    output_schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.screenshot',
    organization_id: undefined,
    slug: 'browser.screenshot',
    metadata: {
      name: 'browser.screenshot',
      display_name: 'Browser Screenshot',
      description: 'Take a screenshot of the page',
      icon: 'camera',
      category: 'browser',
      tags: ['browser', 'screenshot', 'capture'],
      provider: 'browser',
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
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
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
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.extract',
    organization_id: undefined,
    slug: 'browser.extract',
    metadata: {
      name: 'browser.extract',
      display_name: 'Browser Extract',
      description: 'Extract data from the page',
      icon: 'scissors',
      category: 'browser',
      tags: ['browser', 'extract', 'scrape'],
      provider: 'browser',
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
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
        selector: { type: 'string' },
        attribute: { type: 'string' },
        multiple: { type: 'boolean', default: false },
      },
      required: ['sessionId', 'selector'],
    },
    output_schema: {
      type: 'object',
      properties: {
        data: { type: ['string', 'array', 'object'] },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.upload',
    organization_id: undefined,
    slug: 'browser.upload',
    metadata: {
      name: 'browser.upload',
      display_name: 'Browser Upload',
      description: 'Upload files',
      icon: 'upload',
      category: 'browser',
      tags: ['browser', 'upload', 'file'],
      provider: 'browser',
      version: '1.0.0',
      capabilities: ['browser_control', 'write', 'filesystem'],
      risk_level: 'HIGH',
      execution_mode: 'SYNC',
      timeout: 60000,
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: false,
      trust_level: 'ORGANIZATION',
    },
    input_schema: {
      type: 'object',
      properties: {
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
        selector: { type: 'string' },
        files: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              name: { type: 'string' },
              mimeType: { type: 'string' },
              data: { type: 'string', format: 'base64' },
            },
            required: ['name', 'mimeType', 'data'],
          },
        },
      },
      required: ['sessionId', 'selector', 'files'],
    },
    output_schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.download',
    organization_id: undefined,
    slug: 'browser.download',
    metadata: {
      name: 'browser.download',
      display_name: 'Browser Download',
      description: 'Download a file',
      icon: 'download',
      category: 'browser',
      tags: ['browser', 'download', 'file'],
      provider: 'browser',
      version: '1.0.0',
      capabilities: ['browser_control', 'read', 'filesystem'],
      risk_level: 'MEDIUM',
      execution_mode: 'SYNC',
      timeout: 120000,
      supports_streaming: false,
      supports_cancellation: true,
      supports_idempotency: false,
      trust_level: 'ORGANIZATION',
    },
    input_schema: {
      type: 'object',
      properties: {
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
        selector: { type: 'string' },
        suggestedFilename: { type: 'string' },
      },
      required: ['sessionId', 'selector'],
    },
    output_schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        fileName: { type: 'string' },
        fileSize: { type: 'number' },
        mimeType: { type: 'string' },
        storageRef: { type: 'string' },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.tabs',
    organization_id: undefined,
    slug: 'browser.tabs',
    metadata: {
      name: 'browser.tabs',
      display_name: 'Browser Tabs',
      description: 'Manage browser tabs',
      icon: 'tabs',
      category: 'browser',
      tags: ['browser', 'tabs', 'window'],
      provider: 'browser',
      version: '1.0.0',
      capabilities: ['browser_control', 'read'],
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
        sessionId: { type: 'string' },
        action: { type: 'string', enum: ['list', 'create', 'close', 'switch', 'focus'], default: 'list' },
        pageId: { type: 'string' },
        url: { type: 'string', format: 'uri' },
        index: { type: 'number' },
      },
      required: ['sessionId'],
    },
    output_schema: {
      type: 'object',
      properties: {
        pages: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              pageId: { type: 'string' },
              url: { type: 'string' },
              title: { type: 'string' },
              isActive: { type: 'boolean' },
            },
          },
        },
        currentPageId: { type: 'string' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.back',
    organization_id: undefined,
    slug: 'browser.back',
    metadata: {
      name: 'browser.back',
      display_name: 'Browser Back',
      description: 'Navigate back in history',
      icon: 'arrow-left',
      category: 'browser',
      tags: ['browser', 'back', 'history'],
      provider: 'browser',
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
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
      },
      required: ['sessionId', 'pageId'],
    },
    output_schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        url: { type: 'string' },
        title: { type: 'string' },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.forward',
    organization_id: undefined,
    slug: 'browser.forward',
    metadata: {
      name: 'browser.forward',
      display_name: 'Browser Forward',
      description: 'Navigate forward in history',
      icon: 'arrow-right',
      category: 'browser',
      tags: ['browser', 'forward', 'history'],
      provider: 'browser',
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
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
      },
      required: ['sessionId', 'pageId'],
    },
    output_schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        url: { type: 'string' },
        title: { type: 'string' },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.reload',
    organization_id: undefined,
    slug: 'browser.reload',
    metadata: {
      name: 'browser.reload',
      display_name: 'Browser Reload',
      description: 'Reload the current page',
      icon: 'refresh-cw',
      category: 'browser',
      tags: ['browser', 'reload', 'refresh'],
      provider: 'browser',
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
        sessionId: { type: 'string' },
        pageId: { type: 'string' },
        waitUntil: { type: 'string', enum: ['load', 'domcontentloaded', 'networkidle'], default: 'networkidle' },
      },
      required: ['sessionId', 'pageId'],
    },
    output_schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        url: { type: 'string' },
        title: { type: 'string' },
        observation: { type: 'object' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    id: 'browser.close',
    organization_id: undefined,
    slug: 'browser.close',
    metadata: {
      name: 'browser.close',
      display_name: 'Browser Close',
      description: 'Close the browser session',
      icon: 'x',
      category: 'browser',
      tags: ['browser', 'close', 'session'],
      provider: 'browser',
      version: '1.0.0',
      capabilities: ['browser_control'],
      risk_level: 'LOW',
      execution_mode: 'SYNC',
      timeout: 10000,
      supports_streaming: false,
      supports_cancellation: false,
      supports_idempotency: true,
      trust_level: 'ORGANIZATION',
    },
    input_schema: {
      type: 'object',
      properties: {
        sessionId: { type: 'string' },
        force: { type: 'boolean', default: false },
      },
      required: ['sessionId'],
    },
    output_schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
      },
    },
    status: 'ACTIVE',
    configuration: {},
    created_at: new Date(),
    updated_at: new Date(),
  },
];

export async function registerBrowserTools(registry: any, adapter: BrowserToolAdapter): Promise<void> {
  for (const tool of BROWSER_TOOL_DEFINITIONS) {
    registry.register(tool);
  }
  // Register adapter with execution runtime
  // This would be done externally
}