import {
  BrowserActionType,
  BrowserAction,
  BrowserActionResult,
  BrowserActionRiskLevel,
} from '../core/types';
import type {
  BrowserElementHandle,
  BrowserPage,
  BrowserFrame,
} from '../providers/types';
import { createChildLogger } from '@openagent/logger';

const logger = createChildLogger({ module: 'browser:actions' });

export interface ActionExecutor {
  execute(action: BrowserAction, page: BrowserPage, frame?: BrowserFrame): Promise<BrowserActionResult>;
}

export interface ElementTargetingStrategy {
  readonly name: string;
  readonly priority: number;
  findElement(page: BrowserPage, frame: BrowserFrame | null, criteria: ElementCriteria): Promise<BrowserElementHandle | null>;
  findElements(page: BrowserPage, frame: BrowserFrame | null, criteria: ElementCriteria): Promise<BrowserElementHandle[]>;
}

export interface ElementCriteria {
  selector?: string;
  xpath?: string;
  role?: string;
  name?: string;
  label?: string;
  placeholder?: string;
  testId?: string;
  text?: string;
  coordinates?: { x: number; y: number };
  index?: number;
}

export class ElementTargetingEngine {
  private strategies: ElementTargetingStrategy[] = [];

  constructor() {
    this.registerDefaultStrategies();
  }

  registerStrategy(strategy: ElementTargetingStrategy): void {
    this.strategies.push(strategy);
    this.strategies.sort((a, b) => b.priority - a.priority);
  }

  async findElement(page: BrowserPage, frame: BrowserFrame | null, criteria: ElementCriteria): Promise<BrowserElementHandle | null> {
    for (const strategy of this.strategies) {
      try {
        const element = await strategy.findElement(page, frame, criteria);
        if (element) {
          logger.debug('Element found', { strategy: strategy.name, criteria });
          return element;
        }
      } catch (error) {
        logger.debug('Strategy failed', { strategy: strategy.name, error: String(error) });
      }
    }
    return null;
  }

  async findElements(page: BrowserPage, frame: BrowserFrame | null, criteria: ElementCriteria): Promise<BrowserElementHandle[]> {
    const results: BrowserElementHandle[] = [];
    for (const strategy of this.strategies) {
      try {
        const elements = await strategy.findElements(page, frame, criteria);
        results.push(...elements);
      } catch (error) {
        logger.debug('Strategy failed for multiple', { strategy: strategy.name, error: String(error) });
      }
    }
    return results;
  }

  private registerDefaultStrategies(): void {
    // Test ID strategy (highest priority for reliability)
    this.registerStrategy({
      name: 'test-id',
      priority: 100,
      async findElement(page, frame, criteria) {
        if (!criteria.testId) return null;
        const selector = `[data-testid="${criteria.testId}"]`;
        return frame 
          ? frame.waitForSelector(selector, { state: 'visible', timeout: 5000 })
          : page.waitForSelector(selector, { state: 'visible', timeout: 5000 });
      },
      async findElements(page, frame, criteria) {
        if (!criteria.testId) return [];
        const selector = `[data-testid="${criteria.testId}"]`;
        const elements = frame 
          ? await frame.evaluateHandle(`document.querySelectorAll('${selector}')`)
          : await page.evaluateHandle(`document.querySelectorAll('${selector}')`);
        // Convert to handles - simplified
        return [];
      },
    });

    // Role + Name (accessibility)
    this.registerStrategy({
      name: 'role-name',
      priority: 90,
      async findElement(page, frame, criteria) {
        if (!criteria.role) return null;
        let selector = `[role="${criteria.role}"]`;
        if (criteria.name) {
          selector += `[aria-label="${criteria.name}"], [aria-labelledby="${criteria.name}"]`;
        }
        return frame 
          ? frame.waitForSelector(selector, { state: 'visible', timeout: 5000 })
          : page.waitForSelector(selector, { state: 'visible', timeout: 5000 });
      },
      async findElements() { return []; },
    });

    // Label
    this.registerStrategy({
      name: 'label',
      priority: 80,
      async findElement(page, frame, criteria) {
        if (!criteria.label) return null;
        const selector = `label:has-text("${criteria.label}") input, label:has-text("${criteria.label}") select, label:has-text("${criteria.label}") textarea, [aria-label="${criteria.label}"]`;
        return frame 
          ? frame.waitForSelector(selector, { state: 'visible', timeout: 5000 })
          : page.waitForSelector(selector, { state: 'visible', timeout: 5000 });
      },
      async findElements() { return []; },
    });

    // Placeholder
    this.registerStrategy({
      name: 'placeholder',
      priority: 70,
      async findElement(page, frame, criteria) {
        if (!criteria.placeholder) return null;
        const selector = `[placeholder="${criteria.placeholder}"]`;
        return frame 
          ? frame.waitForSelector(selector, { state: 'visible', timeout: 5000 })
          : page.waitForSelector(selector, { state: 'visible', timeout: 5000 });
      },
      async findElements() { return []; },
    });

    // Text content
    this.registerStrategy({
      name: 'text',
      priority: 60,
      async findElement(page, frame, criteria) {
        if (!criteria.text) return null;
        const selector = `:text("${criteria.text}")`;
        return frame 
          ? frame.waitForSelector(selector, { state: 'visible', timeout: 5000 })
          : page.waitForSelector(selector, { state: 'visible', timeout: 5000 });
      },
      async findElements() { return []; },
    });

    // CSS Selector
    this.registerStrategy({
      name: 'css-selector',
      priority: 50,
      async findElement(page, frame, criteria) {
        if (!criteria.selector) return null;
        return frame 
          ? frame.waitForSelector(criteria.selector, { state: 'visible', timeout: 5000 })
          : page.waitForSelector(criteria.selector, { state: 'visible', timeout: 5000 });
      },
      async findElements() { return []; },
    });

    // XPath
    this.registerStrategy({
      name: 'xpath',
      priority: 40,
      async findElement(page, frame, criteria) {
        if (!criteria.xpath) return null;
        const selector = `xpath=${criteria.xpath}`;
        return frame 
          ? frame.waitForSelector(selector, { state: 'visible', timeout: 5000 })
          : page.waitForSelector(selector, { state: 'visible', timeout: 5000 });
      },
      async findElements() { return []; },
    });

    // Coordinates (lowest priority - least reliable)
    this.registerStrategy({
      name: 'coordinates',
      priority: 10,
      async findElement(page, frame, criteria) {
        if (!criteria.coordinates) return null;
        // Use elementFromPoint
        const target = frame ?? page;
        const element = await target.evaluate(
          '([x, y]) => { const el = document.elementFromPoint(x, y); return el ? el.outerHTML.slice(0, 200) : null; }',
          [criteria.coordinates.x, criteria.coordinates.y],
        );
        return element as unknown as BrowserElementHandle;
      },
      async findElements() { return []; },
    });
  }
}

export class ActionExecutorRegistry {
  private executors: Map<BrowserActionType, ActionExecutor> = new Map();

  register(actionType: BrowserActionType, executor: ActionExecutor): void {
    this.executors.set(actionType, executor);
  }

  get(actionType: BrowserActionType): ActionExecutor | undefined {
    return this.executors.get(actionType);
  }

  async execute(action: BrowserAction, page: BrowserPage, frame?: BrowserFrame): Promise<BrowserActionResult> {
    const executor = this.executors.get(action.type);
    if (!executor) {
      return {
        success: false,
        error: {
          code: 'UNSUPPORTED_ACTION',
          message: `Action type ${action.type} not supported`,
          retryable: false,
        },
      };
    }

    try {
      return await executor.execute(action, page, frame);
    } catch (error) {
      logger.error('Action execution failed', { actionId: action.id, type: action.type, error: String(error) });
      return {
        success: false,
        error: {
          code: 'EXECUTION_FAILED',
          message: String(error),
          retryable: this.isRetryableError(error),
        },
      };
    }
  }

  private isRetryableError(error: unknown): boolean {
    if (error instanceof Error) {
      const retryableMessages = ['timeout', 'navigation', 'network', 'detached', 'stale'];
      return retryableMessages.some(m => error.message.toLowerCase().includes(m));
    }
    return false;
  }
}

export const actionExecutorRegistry = new ActionExecutorRegistry();
export const elementTargetingEngine = new ElementTargetingEngine();

export interface ActionContext {
  sessionId: string;
  pageId: string;
  frameId?: string;
  organizationId: string;
  agentId?: string;
  taskId?: string;
}

export interface ActionValidationResult {
  valid: boolean;
  errors: string[];
  riskLevel: BrowserActionRiskLevel;
  requiresApproval: boolean;
}

export class ActionValidator {
  private riskLevels: Map<BrowserActionType, BrowserActionRiskLevel> = new Map([
    ['NAVIGATE', 'MEDIUM'],
    ['CLICK', 'MEDIUM'],
    ['DOUBLE_CLICK', 'MEDIUM'],
    ['TYPE', 'MEDIUM'],
    ['FILL', 'MEDIUM'],
    ['SELECT', 'MEDIUM'],
    ['CHECK', 'MEDIUM'],
    ['UNCHECK', 'MEDIUM'],
    ['HOVER', 'LOW'],
    ['SCROLL', 'LOW'],
    ['PRESS_KEY', 'MEDIUM'],
    ['DRAG', 'MEDIUM'],
    ['DROP', 'MEDIUM'],
    ['WAIT', 'LOW'],
    ['SCREENSHOT', 'LOW'],
    ['EXTRACT', 'LOW'],
    ['UPLOAD', 'HIGH'],
    ['DOWNLOAD', 'MEDIUM'],
    ['SWITCH_TAB', 'LOW'],
    ['GO_BACK', 'LOW'],
    ['GO_FORWARD', 'LOW'],
    ['RELOAD', 'LOW'],
    ['FOCUS', 'LOW'],
    ['EVALUATE', 'HIGH'],
    ['SET_VIEWPORT', 'LOW'],
    ['SET_COOKIE', 'MEDIUM'],
    ['CLEAR_COOKIES', 'MEDIUM'],
    ['GET_COOKIES', 'LOW'],
    ['AUTHENTICATE', 'CRITICAL'],
    ['HANDLE_DIALOG', 'MEDIUM'],
    ['WAIT_FOR_SELECTOR', 'LOW'],
    ['WAIT_FOR_NAVIGATION', 'LOW'],
    ['WAIT_FOR_FUNCTION', 'LOW'],
    ['SELECT_OPTION', 'MEDIUM'],
    ['SET_INPUT_FILES', 'HIGH'],
    ['CHECKBOX', 'MEDIUM'],
    ['RADIO', 'MEDIUM'],
  ]);

  private approvalRequired: BrowserActionType[] = [
    'UPLOAD',
    'DOWNLOAD',
    'AUTHENTICATE',
    'EVALUATE',
    'SET_INPUT_FILES',
  ];

  validate(action: BrowserAction, context: ActionContext): ActionValidationResult {
    const errors: string[] = [];
    const riskLevel = this.riskLevels.get(action.type) || 'MEDIUM';
    const requiresApproval = this.approvalRequired.includes(action.type);

    // Basic validation
    if (!action.input || typeof action.input !== 'object') {
      errors.push('Action input must be an object');
    }

    // Type-specific validation
    switch (action.type) {
      case 'NAVIGATE':
        if (!action.input.url || typeof action.input.url !== 'string') {
          errors.push('NAVIGATE requires url parameter');
        }
        break;
      case 'CLICK':
      case 'DOUBLE_CLICK':
      case 'HOVER':
      case 'FOCUS':
        if (!action.input.selector && !action.input.coordinates) {
          errors.push(`${action.type} requires selector or coordinates`);
        }
        break;
      case 'TYPE':
      case 'FILL':
        if (!action.input.selector) {
          errors.push(`${action.type} requires selector`);
        }
        if (action.type === 'TYPE' && !action.input.text) {
          errors.push('TYPE requires text parameter');
        }
        if (action.type === 'FILL' && action.input.value === undefined) {
          errors.push('FILL requires value parameter');
        }
        break;
      case 'SELECT':
      case 'CHECK':
      case 'UNCHECK':
      case 'CHECKBOX':
      case 'RADIO':
        if (!action.input.selector) {
          errors.push(`${action.type} requires selector`);
        }
        break;
      case 'SCROLL':
        // Optional parameters
        break;
      case 'PRESS_KEY':
        if (!action.input.key) {
          errors.push('PRESS_KEY requires key parameter');
        }
        break;
      case 'DRAG':
      case 'DROP':
        if (!action.input.source || !action.input.target) {
          errors.push(`${action.type} requires source and target`);
        }
        break;
      case 'SCREENSHOT':
        // Optional parameters
        break;
      case 'EXTRACT':
        if (!action.input.selector) {
          errors.push('EXTRACT requires selector');
        }
        break;
      case 'UPLOAD':
        if (!action.input.selector || !action.input.files) {
          errors.push('UPLOAD requires selector and files');
        }
        break;
      case 'DOWNLOAD':
        if (!action.input.selector) {
          errors.push('DOWNLOAD requires selector');
        }
        break;
      case 'SWITCH_TAB':
        if (!action.input.pageId && action.input.index === undefined) {
          errors.push('SWITCH_TAB requires pageId or index');
        }
        break;
      case 'EVALUATE':
        if (!action.input.script) {
          errors.push('EVALUATE requires script parameter');
        }
        break;
      case 'SET_COOKIE':
        if (!action.input.cookie) {
          errors.push('SET_COOKIE requires cookie parameter');
        }
        break;
    }

    return {
      valid: errors.length === 0,
      errors,
      riskLevel,
      requiresApproval,
    };
  }

  getRiskLevel(actionType: BrowserActionType): BrowserActionRiskLevel {
    return this.riskLevels.get(actionType) || 'MEDIUM';
  }

  requiresApproval(actionType: BrowserActionType): boolean {
    return this.approvalRequired.includes(actionType);
  }
}

export const actionValidator = new ActionValidator();