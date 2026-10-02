import { ToolRateLimitConfig } from './types';
import { OpenAgentLogger, createChildLogger } from '@openagent/logger';

const logger: OpenAgentLogger = createChildLogger({ module: 'tool-system:rate-limiter' });

interface RateLimitBucket {
  count: number;
  resetTime: number;
  concurrent: number;
}

interface DailyLimitBucket {
  count: number;
  date: string;
}

export class RateLimiter {
  private config: ToolRateLimitConfig;
  private minuteBuckets: Map<string, RateLimitBucket> = new Map();
  private dailyBuckets: Map<string, DailyLimitBucket> = new Map();
  private concurrentCounts: Map<string, number> = new Map();
  private cleanupInterval: NodeJS.Timeout;

  constructor(config: ToolRateLimitConfig) {
    this.config = config;
    this.cleanupInterval = setInterval(() => this.cleanup(), 60000);
  }

  async checkLimit(
    organizationId: string,
    userId?: string,
    agentId?: string
  ): Promise<void> {
    const keys = this.getLimitKeys(organizationId, userId, agentId);

    for (const key of keys) {
      await this.checkMinuteLimit(key);
      await this.checkConcurrentLimit(key);
      await this.checkDailyLimit(key);
    }
  }

  private getLimitKeys(
    organizationId: string,
    userId?: string,
    agentId?: string
  ): string[] {
    const keys = [`org:${organizationId}`];
    if (userId) keys.push(`user:${userId}`);
    if (agentId) keys.push(`agent:${agentId}`);
    if (userId && agentId) keys.push(`user:${userId}:agent:${agentId}`);
    return keys;
  }

  private async checkMinuteLimit(key: string): Promise<void> {
    const now = Date.now();
    const minuteKey = `${key}:${Math.floor(now / 60000)}`;
    const bucket = this.minuteBuckets.get(minuteKey) || { count: 0, resetTime: now + 60000, concurrent: 0 };

    if (bucket.count >= this.config.requests_per_minute) {
      const retryAfter = Math.ceil((bucket.resetTime - now) / 1000);
      throw new RateLimitExceededError('RATE_LIMIT_EXCEEDED', `Rate limit exceeded for ${key}`, retryAfter);
    }

    bucket.count++;
    this.minuteBuckets.set(minuteKey, bucket);
  }

  private async checkConcurrentLimit(key: string): Promise<void> {
    const current = this.concurrentCounts.get(key) || 0;
    if (current >= this.config.concurrent_executions) {
      throw new RateLimitExceededError(
        'CONCURRENT_LIMIT_EXCEEDED',
        `Concurrent execution limit exceeded for ${key}`,
        1
      );
    }

    this.concurrentCounts.set(key, current + 1);
  }

  private async checkDailyLimit(key: string): Promise<void> {
    const today = new Date().toISOString().split('T')[0];
    const dailyKey = `${key}:${today}`;
    const bucket = this.dailyBuckets.get(dailyKey) || { count: 0, date: today };

    const limit = this.getDailyLimit(key);
    if (bucket.count >= limit) {
      const tomorrow = new Date();
      tomorrow.setDate(tomorrow.getDate() + 1);
      tomorrow.setHours(0, 0, 0, 0);
      const retryAfter = Math.ceil((tomorrow.getTime() - Date.now()) / 1000);
      throw new RateLimitExceededError('DAILY_LIMIT_EXCEEDED', `Daily limit exceeded for ${key}`, retryAfter);
    }

    bucket.count++;
    this.dailyBuckets.set(dailyKey, bucket);
  }

  private getDailyLimit(key: string): number {
    if (key.startsWith('org:') && this.config.organization_quota) {
      return this.config.organization_quota;
    }
    if (key.startsWith('agent:') && this.config.agent_quota) {
      return this.config.agent_quota;
    }
    if (key.startsWith('user:') && this.config.user_quota) {
      return this.config.user_quota;
    }
    return this.config.daily_execution_limit;
  }

  releaseConcurrent(organizationId: string, userId?: string, agentId?: string): void {
    const keys = this.getLimitKeys(organizationId, userId, agentId);
    for (const key of keys) {
      const current = this.concurrentCounts.get(key) || 0;
      if (current > 0) {
        this.concurrentCounts.set(key, current - 1);
      }
    }
  }

  getUsage(organizationId: string, userId?: string, agentId?: string): Record<string, { used: number; limit: number }> {
    const keys = this.getLimitKeys(organizationId, userId, agentId);
    const usage: Record<string, { used: number; limit: number }> = {};

    for (const key of keys) {
      const now = Date.now();
      const minuteKey = `${key}:${Math.floor(now / 60000)}`;
      const minuteBucket = this.minuteBuckets.get(minuteKey) || { count: 0, resetTime: 0, concurrent: 0 };
      const concurrent = this.concurrentCounts.get(key) || 0;
      const today = new Date().toISOString().split('T')[0];
      const dailyKey = `${key}:${today}`;
      const dailyBucket = this.dailyBuckets.get(dailyKey) || { count: 0, date: today };

      usage[`${key}:minute`] = { used: minuteBucket.count, limit: this.config.requests_per_minute };
      usage[`${key}:concurrent`] = { used: concurrent, limit: this.config.concurrent_executions };
      usage[`${key}:daily`] = { used: dailyBucket.count, limit: this.getDailyLimit(key) };
    }

    return usage;
  }

  reset(organizationId: string, userId?: string, agentId?: string): void {
    const keys = this.getLimitKeys(organizationId, userId, agentId);
    for (const key of keys) {
      const now = Date.now();
      const minuteKey = `${key}:${Math.floor(now / 60000)}`;
      this.minuteBuckets.delete(minuteKey);
      this.concurrentCounts.delete(key);
      const today = new Date().toISOString().split('T')[0];
      const dailyKey = `${key}:${today}`;
      this.dailyBuckets.delete(dailyKey);
    }
  }

  private cleanup(): void {
    const now = Date.now();
    const today = new Date().toISOString().split('T')[0];

    for (const [key, bucket] of this.minuteBuckets.entries()) {
      if (bucket.resetTime < now) {
        this.minuteBuckets.delete(key);
      }
    }

    for (const [key, bucket] of this.dailyBuckets.entries()) {
      if (bucket.date !== today) {
        this.dailyBuckets.delete(key);
      }
    }
  }

  shutdown(): void {
    clearInterval(this.cleanupInterval);
  }
}

export class RateLimitExceededError extends Error {
  public readonly code: string;
  public readonly retryAfter: number;

  constructor(code: string, message: string, retryAfter: number) {
    super(message);
    this.name = 'RateLimitExceededError';
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

export function createRateLimiter(config?: Partial<ToolRateLimitConfig>): RateLimiter {
  const defaultConfig: ToolRateLimitConfig = {
    requests_per_minute: 60,
    concurrent_executions: 10,
    daily_execution_limit: 10000,
    organization_quota: 100000,
    agent_quota: 1000,
    user_quota: 5000,
    ...config,
  };
  return new RateLimiter(defaultConfig);
}