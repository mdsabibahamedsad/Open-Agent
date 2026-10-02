import {
  BrowserTask,
  BrowserTaskStatus,
  BrowserAction,
  BrowserActionType,
  BrowserActionRiskLevel,
  BrowserActionResult,
  BrowserObservation,
  BrowserTaskRiskPolicy,
  BrowserStateFingerprint,
} from '../core/types';
import { OpenAgentLogger, createChildLogger } from '@openagent/logger';

const logger = createChildLogger({ module: 'browser:tasks' });

export interface TaskManagerConfig {
  maxSteps: number;
  defaultTimeout: number;
  maxRetries: number;
  enableLoopDetection: boolean;
  loopDetectionThreshold: number;
  persistInterval: number;
  recoveryEnabled: boolean;
}

export const defaultTaskManagerConfig: TaskManagerConfig = {
  maxSteps: 100,
  defaultTimeout: 300000, // 5 minutes
  maxRetries: 2,
  enableLoopDetection: true,
  loopDetectionThreshold: 3,
  persistInterval: 5000, // 5 seconds
  recoveryEnabled: true,
};

export interface PersistedTaskState {
  task: BrowserTask;
  actions: BrowserAction[];
  observations: BrowserObservation[];
  fingerprints: BrowserStateFingerprint[];
  currentStep: number;
  lastPersisted: Date;
}

export class BrowserTaskManager {
  private config: TaskManagerConfig;
  private tasks: Map<string, BrowserTask> = new Map();
  private taskActions: Map<string, BrowserAction[]> = new Map();
  private taskObservations: Map<string, BrowserObservation[]> = new Map();
  private taskFingerprints: Map<string, BrowserStateFingerprint[]> = new Map();
  private persistTimers: Map<string, NodeJS.Timeout> = new Map();
  private loopDetector: LoopDetector;

  constructor(config: Partial<TaskManagerConfig> = {}) {
    this.config = { ...defaultTaskManagerConfig, ...config };
    this.loopDetector = new LoopDetector(this.config.loopDetectionThreshold);
  }

  async createTask(params: {
    organizationId: string;
    agentId?: string;
    workflowExecutionId?: string;
    browserSessionId: string;
    objective: string;
    maxSteps?: number;
    timeout?: number;
    riskPolicy?: Partial<BrowserTaskRiskPolicy>;
    metadata?: Record<string, unknown>;
  }): Promise<BrowserTask> {
    const taskId = `task_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    const now = new Date();

    const task: BrowserTask = {
      taskId,
      organizationId: params.organizationId,
      agentId: params.agentId,
      workflowExecutionId: params.workflowExecutionId,
      browserSessionId: params.browserSessionId,
      status: 'QUEUED',
      objective: params.objective,
      currentStep: 0,
      maxSteps: params.maxSteps || this.config.maxSteps,
      timeout: params.timeout || this.config.defaultTimeout,
      riskPolicy: {
        allowedRiskLevels: ['LOW', 'MEDIUM'],
        maxRiskLevel: 'MEDIUM',
        requireApprovalFor: ['HIGH', 'CRITICAL'],
        blockedActions: [],
        ...params.riskPolicy,
      },
      createdAt: now,
      updatedAt: now,
      metadata: params.metadata || {},
    };

    this.tasks.set(taskId, task);
    this.taskActions.set(taskId, []);
    this.taskObservations.set(taskId, []);
    this.taskFingerprints.set(taskId, []);

    // Start persistence timer
    this.startPersistenceTimer(taskId);

    logger.info('Browser task created', { taskId, organizationId: params.organizationId });
    return task;
  }

  async getTask(taskId: string): Promise<BrowserTask | null> {
    return this.tasks.get(taskId) || null;
  }

  async updateTaskStatus(taskId: string, status: BrowserTaskStatus): Promise<void> {
    const task = this.tasks.get(taskId);
    if (task) {
      task.status = status;
      task.updatedAt = new Date();
      if (status === 'SUCCEEDED' || status === 'FAILED' || status === 'CANCELLED' || status === 'TIMED_OUT') {
        task.completedAt = new Date();
        this.stopPersistenceTimer(taskId);
      }
    }
  }

  async updateTaskProgress(taskId: string, updates: {
    currentUrl?: string;
    currentPageId?: string;
    currentStep?: number;
    metadata?: Record<string, unknown>;
  }): Promise<void> {
    const task = this.tasks.get(taskId);
    if (task) {
      if (updates.currentUrl) task.currentUrl = updates.currentUrl;
      if (updates.currentPageId) task.currentPageId = updates.currentPageId;
      if (updates.currentStep !== undefined) task.currentStep = updates.currentStep;
      if (updates.metadata) task.metadata = { ...task.metadata, ...updates.metadata };
      task.updatedAt = new Date();
    }
  }

  async addAction(taskId: string, action: BrowserAction): Promise<void> {
    const actions = this.taskActions.get(taskId) || [];
    actions.push(action);
    this.taskActions.set(taskId, actions);
  }

  async updateActionResult(taskId: string, actionId: string, result: BrowserActionResult): Promise<void> {
    const actions = this.taskActions.get(taskId) || [];
    const action = actions.find(a => a.id === actionId);
    if (action) {
      action.result = result;
      action.status = result.success ? 'SUCCEEDED' : 'FAILED';
      action.completedAt = new Date();
      if (action.startedAt) {
        action.durationMs = action.completedAt.getTime() - action.startedAt.getTime();
      }
    }
  }

  async addObservation(taskId: string, observation: BrowserObservation): Promise<void> {
    const observations = this.taskObservations.get(taskId) || [];
    observations.push(observation);
    this.taskObservations.set(taskId, observations);
  }

  async addFingerprint(taskId: string, fingerprint: BrowserStateFingerprint): Promise<void> {
    const fingerprints = this.taskFingerprints.get(taskId) || [];
    fingerprints.push(fingerprint);
    this.taskFingerprints.set(taskId, fingerprints);

    // Check for loops
    if (this.config.enableLoopDetection) {
      const loopDetected = this.loopDetector.check(fingerprints);
      if (loopDetected) {
        logger.warn('Loop detected in browser task', { taskId, loopType: loopDetected.type });
        // Could trigger replanning or human intervention
      }
    }
  }

  async getTaskState(taskId: string): Promise<PersistedTaskState | null> {
    const task = this.tasks.get(taskId);
    if (!task) return null;

    return {
      task,
      actions: this.taskActions.get(taskId) || [],
      observations: this.taskObservations.get(taskId) || [],
      fingerprints: this.taskFingerprints.get(taskId) || [],
      currentStep: task.currentStep,
      lastPersisted: new Date(),
    };
  }

  async persistTask(taskId: string): Promise<void> {
    const state = await this.getTaskState(taskId);
    if (state) {
      // In a real implementation, this would save to database
      logger.debug('Task state persisted', { taskId, actions: state.actions.length, observations: state.observations.length });
    }
  }

  async recoverTask(taskId: string): Promise<PersistedTaskState | null> {
    // In a real implementation, this would load from database
    logger.info('Attempting task recovery', { taskId });
    return this.getTaskState(taskId);
  }

  async cancelTask(taskId: string): Promise<void> {
    await this.updateTaskStatus(taskId, 'CANCELLED');
    this.stopPersistenceTimer(taskId);
    logger.info('Browser task cancelled', { taskId });
  }

  async pauseTask(taskId: string): Promise<void> {
    await this.updateTaskStatus(taskId, 'PAUSED');
    logger.info('Browser task paused', { taskId });
  }

  async resumeTask(taskId: string): Promise<void> {
    const task = this.tasks.get(taskId);
    if (task && task.status === 'PAUSED') {
      task.status = 'RUNNING';
      task.updatedAt = new Date();
      logger.info('Browser task resumed', { taskId });
    }
  }

  async listTasks(filters?: {
    organizationId?: string;
    agentId?: string;
    workflowExecutionId?: string;
    browserSessionId?: string;
    status?: BrowserTaskStatus;
  }): Promise<BrowserTask[]> {
    let tasks = Array.from(this.tasks.values());

    if (filters) {
      if (filters.organizationId) tasks = tasks.filter(t => t.organizationId === filters.organizationId);
      if (filters.agentId) tasks = tasks.filter(t => t.agentId === filters.agentId);
      if (filters.workflowExecutionId) tasks = tasks.filter(t => t.workflowExecutionId === filters.workflowExecutionId);
      if (filters.browserSessionId) tasks = tasks.filter(t => t.browserSessionId === filters.browserSessionId);
      if (filters.status) tasks = tasks.filter(t => t.status === filters.status);
    }

    return tasks;
  }

  private startPersistenceTimer(taskId: string): void {
    const timer = setInterval(async () => {
      await this.persistTask(taskId);
    }, this.config.persistInterval);
    this.persistTimers.set(taskId, timer);
  }

  private stopPersistenceTimer(taskId: string): void {
    const timer = this.persistTimers.get(taskId);
    if (timer) {
      clearInterval(timer);
      this.persistTimers.delete(taskId);
    }
  }

  async shutdown(): Promise<void> {
    for (const [taskId, timer] of this.persistTimers.entries()) {
      clearInterval(timer);
      await this.persistTask(taskId);
    }
    this.persistTimers.clear();
  }
}

export class LoopDetector {
  private threshold: number;
  private urlHistory: Map<string, number> = new Map();
  private actionHistory: Map<string, number> = new Map();
  private domHashHistory: Map<string, number> = new Map();

  constructor(threshold: number) {
    this.threshold = threshold;
  }

  check(fingerprints: BrowserStateFingerprint[]): { type: string; details: string } | null {
    if (fingerprints.length < this.threshold) return null;

    const recent = fingerprints.slice(-this.threshold * 2);
    
    // Check URL repetition
    const urlCounts = new Map<string, number>();
    for (const fp of recent) {
      urlCounts.set(fp.url, (urlCounts.get(fp.url) || 0) + 1);
    }
    for (const [url, count] of urlCounts.entries()) {
      if (count >= this.threshold) {
        return { type: 'url_repetition', details: `URL repeated ${count} times: ${url}` };
      }
    }

    // Check DOM hash repetition
    const domCounts = new Map<string, number>();
    for (const fp of recent) {
      domCounts.set(fp.domHash, (domCounts.get(fp.domHash) || 0) + 1);
    }
    for (const [hash, count] of domCounts.entries()) {
      if (count >= this.threshold) {
        return { type: 'dom_repetition', details: `DOM state repeated ${count} times` };
      }
    }

    // Check action patterns (would need action history)
    
    return null;
  }

  recordAction(actionType: BrowserActionType): void {
    const key = actionType;
    this.actionHistory.set(key, (this.actionHistory.get(key) || 0) + 1);
  }

  recordUrl(url: string): void {
    this.urlHistory.set(url, (this.urlHistory.get(url) || 0) + 1);
  }

  recordDomHash(hash: string): void {
    this.domHashHistory.set(hash, (this.domHashHistory.get(hash) || 0) + 1);
  }

  reset(): void {
    this.urlHistory.clear();
    this.actionHistory.clear();
    this.domHashHistory.clear();
  }
}

export class TaskPlanner {
  private maxSteps: number;

  constructor(maxSteps: number = 100) {
    this.maxSteps = maxSteps;
  }

  async createPlan(objective: string, context: { url?: string; observations?: BrowserObservation[] }): Promise<Plan> {
    // This would use an LLM to create a plan
    // For now, return a basic plan structure
    return {
      goal: objective,
      steps: [
        {
          step: 1,
          description: 'Navigate to target website',
          action: 'NAVIGATE',
          expectedOutcome: 'Page loaded successfully',
        },
        {
          step: 2,
          description: 'Inspect page for interactive elements',
          action: 'EXTRACT',
          expectedOutcome: 'List of actionable elements',
        },
      ],
      estimatedSteps: 2,
    };
  }

  async updatePlan(plan: Plan, observation: BrowserObservation, previousAction?: BrowserAction): Promise<Plan> {
    // Replan based on observation
    return plan;
  }

  isPlanComplete(plan: Plan, currentStep: number): boolean {
    return currentStep >= plan.steps.length || currentStep >= this.maxSteps;
  }
}

export interface Plan {
  goal: string;
  steps: PlanStep[];
  estimatedSteps: number;
}

export interface PlanStep {
  step: number;
  description: string;
  action: BrowserActionType;
  expectedOutcome: string;
  riskLevel?: BrowserActionRiskLevel;
}

export const browserTaskManager = new BrowserTaskManager();
export const taskPlanner = new TaskPlanner();