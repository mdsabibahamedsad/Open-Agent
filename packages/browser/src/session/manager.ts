import {
  BrowserSessionConfig,
  BrowserSessionStatus,
  BrowserProviderConfig,
  BrowserContextConfig,
  BrowserProviderType,
  BrowserType,
  Viewport,
  Cookie,
  StorageState,
  BrowserProfile,
  BrowserProfileType,
  BrowserSessionLease,
  BrowserStateFingerprint,
} from "../core/types";
import { browserProviderRegistry } from "../providers/types";
import type {
  BrowserContext,
  BrowserPage,
  BrowserProvider,
} from "../providers/types";
import { createChildLogger } from "@openagent/logger";

const logger = createChildLogger({ module: "browser:session-manager" });

export interface SessionManagerConfig {
  defaultProvider: BrowserProviderType;
  defaultBrowserType: BrowserType;
  defaultHeadless: boolean;
  sessionTimeoutMs: number;
  idleTimeoutMs: number;
  heartbeatIntervalMs: number;
  maxConcurrentSessions: number;
  maxSessionsPerUser: number;
  maxSessionsPerOrganization: number;
  cleanupIntervalMs: number;
  artifactRetentionMs: number;
  enableVideoRecording: boolean;
  enableHarRecording: boolean;
  downloadPath: string;
}

export const defaultSessionManagerConfig: SessionManagerConfig = {
  defaultProvider: "playwright",
  defaultBrowserType: "chromium",
  defaultHeadless: true,
  sessionTimeoutMs: 30 * 60 * 1000, // 30 minutes
  idleTimeoutMs: 5 * 60 * 1000, // 5 minutes
  heartbeatIntervalMs: 30 * 1000, // 30 seconds
  maxConcurrentSessions: 100,
  maxSessionsPerUser: 10,
  maxSessionsPerOrganization: 50,
  cleanupIntervalMs: 60 * 1000, // 1 minute
  artifactRetentionMs: 24 * 60 * 60 * 1000, // 24 hours
  enableVideoRecording: false,
  enableHarRecording: false,
  downloadPath: "/tmp/browser-downloads",
};

export interface BrowserSession {
  config: BrowserSessionConfig;
  provider: BrowserProvider;
  context: BrowserContext | null;
  pages: Map<string, BrowserPage>;
  leases: Map<string, BrowserSessionLease>;
  lastHeartbeat: Date;
  stateFingerprint?: BrowserStateFingerprint;
}

export class BrowserSessionManager {
  private sessions: Map<string, BrowserSession> = new Map();
  private config: SessionManagerConfig;
  private cleanupTimer?: NodeJS.Timeout;
  private heartbeatTimer?: NodeJS.Timeout;
  private sessionCounter = 0;

  constructor(config: Partial<SessionManagerConfig> = {}) {
    this.config = { ...defaultSessionManagerConfig, ...config };
  }

  async initialize(): Promise<void> {
    this.startCleanupTimer();
    this.startHeartbeatTimer();
    logger.info("Browser session manager initialized", { config: this.config });
  }

  async createSession(params: {
    organizationId: string;
    userId?: string;
    agentId?: string;
    workflowExecutionId?: string;
    browserProfileId?: string;
    providerConfig?: Partial<BrowserProviderConfig>;
    headless?: boolean;
    metadata?: Record<string, unknown>;
  }): Promise<BrowserSessionConfig> {
    // Check limits
    await this.checkLimits(params.organizationId, params.userId);

    const sessionId = `session_${Date.now()}_${++this.sessionCounter}_${Math.random().toString(36).substr(2, 9)}`;
    const now = new Date();
    const expiresAt = new Date(now.getTime() + this.config.sessionTimeoutMs);

    const providerConfig: BrowserProviderConfig = {
      type: this.config.defaultProvider,
      browserType: this.config.defaultBrowserType,
      headless: params.headless ?? this.config.defaultHeadless,
      viewport: params.providerConfig?.viewport || { width: 1280, height: 720 },
      timeout: 30000,
      downloadsPath: this.config.downloadPath,
      ...params.providerConfig,
    };

    if (this.config.enableVideoRecording) {
      providerConfig.recordVideo = {
        dir: `${this.config.downloadPath}/videos`,
      };
    }
    if (this.config.enableHarRecording) {
      providerConfig.recordHar = {
        path: `${this.config.downloadPath}/${sessionId}.har`,
      };
    }

    const provider = await browserProviderRegistry.create(
      providerConfig.type,
      providerConfig,
    );

    const sessionConfig: BrowserSessionConfig = {
      sessionId,
      organizationId: params.organizationId,
      userId: params.userId,
      agentId: params.agentId,
      workflowExecutionId: params.workflowExecutionId,
      browserProfileId: params.browserProfileId,
      provider: providerConfig,
      status: "CREATED",
      createdAt: now,
      lastActivityAt: now,
      expiresAt,
      headless: providerConfig.headless ?? this.config.defaultHeadless,
      metadata: params.metadata || {},
    };

    const session: BrowserSession = {
      config: sessionConfig,
      provider,
      context: null,
      pages: new Map(),
      leases: new Map(),
      lastHeartbeat: now,
    };

    this.sessions.set(sessionId, session);

    // Start the browser and create context
    await this.startSession(sessionId);

    logger.info("Browser session created", {
      sessionId,
      organizationId: params.organizationId,
    });
    return sessionConfig;
  }

  private async startSession(sessionId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) throw new Error(`Session ${sessionId} not found`);

    session.config.status = "STARTING";

    try {
      // Create browser context
      const contextConfig: BrowserContextConfig = {
        contextId: `ctx_${sessionId}`,
        sessionId,
        viewport: session.config.provider.viewport,
        userAgent: session.config.provider.userAgent,
        locale: session.config.provider.locale,
        timezoneId: session.config.provider.timezoneId,
        geolocation: session.config.provider.geolocation,
        permissions: session.config.provider.permissions,
        proxy: session.config.provider.proxy,
        offline: session.config.provider.offline,
      };

      session.context = await session.provider.createContext(
        session.config,
        contextConfig,
      );

      // Load profile storage state if available
      // TODO: Load from profile

      session.config.status = "READY";
      session.lastHeartbeat = new Date();

      logger.info("Browser session started", { sessionId });
    } catch (error) {
      session.config.status = "ERROR";
      logger.error("Failed to start browser session", {
        sessionId,
        error: String(error),
      });
      throw error;
    }
  }

  async getSession(sessionId: string): Promise<BrowserSessionConfig | null> {
    const session = this.sessions.get(sessionId);
    return session?.config || null;
  }

  async getSessionInternal(sessionId: string): Promise<BrowserSession | null> {
    return this.sessions.get(sessionId) || null;
  }

  async updateSessionStatus(
    sessionId: string,
    status: BrowserSessionStatus,
  ): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (session) {
      session.config.status = status;
      session.config.lastActivityAt = new Date();
    }
  }

  async pauseSession(sessionId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) throw new Error(`Session ${sessionId} not found`);

    session.config.status = "PAUSED";
    session.config.lastActivityAt = new Date();
    logger.info("Browser session paused", { sessionId });
  }

  async resumeSession(sessionId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) throw new Error(`Session ${sessionId} not found`);

    if (session.config.status === "PAUSED") {
      session.config.status = "READY";
      session.config.lastActivityAt = new Date();
      session.lastHeartbeat = new Date();
      logger.info("Browser session resumed", { sessionId });
    }
  }

  async closeSession(sessionId: string, force = false): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) {
      logger.warn("Attempted to close non-existent session", { sessionId });
      return;
    }

    session.config.status = "CLOSING";

    try {
      // Close all pages
      for (const page of session.pages.values()) {
        try {
          await page.close();
        } catch (error) {
          logger.warn("Error closing page", {
            sessionId,
            pageId: page.pageId,
            error: String(error),
          });
        }
      }
      session.pages.clear();

      // Close context
      if (session.context) {
        await session.context.close();
        session.context = null;
      }

      // Close provider
      await session.provider.close();

      session.config.status = "CLOSED";
      logger.info("Browser session closed", { sessionId });
    } catch (error) {
      session.config.status = "ERROR";
      logger.error("Error closing browser session", {
        sessionId,
        error: String(error),
      });
      if (!force) throw error;
    } finally {
      this.sessions.delete(sessionId);
    }
  }

  async terminateSession(sessionId: string): Promise<void> {
    await this.closeSession(sessionId, true);
  }

  async createPage(
    sessionId: string,
    options?: { url?: string; isPopup?: boolean; openerPageId?: string },
  ): Promise<BrowserPage> {
    const session = this.sessions.get(sessionId);
    if (!session) throw new Error(`Session ${sessionId} not found`);
    if (!session.context)
      throw new Error(`Session ${sessionId} has no context`);

    session.config.status = "BUSY";
    session.config.lastActivityAt = new Date();

    const page = await session.context.newPage();
    session.pages.set(page.pageId, page);

    if (options?.url) {
      await page.goto(options.url);
    }

    session.config.status = "READY";
    return page;
  }

  async getPage(
    sessionId: string,
    pageId: string,
  ): Promise<BrowserPage | null> {
    const session = this.sessions.get(sessionId);
    return session?.pages.get(pageId) || null;
  }

  async closePage(sessionId: string, pageId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) throw new Error(`Session ${sessionId} not found`);

    const page = session.pages.get(pageId);
    if (page) {
      await page.close();
      session.pages.delete(pageId);
    }
  }

  async listPages(sessionId: string): Promise<BrowserPage[]> {
    const session = this.sessions.get(sessionId);
    return session ? Array.from(session.pages.values()) : [];
  }

  async acquireLease(
    sessionId: string,
    holderId: string,
    holderType: "agent" | "workflow" | "human",
    purpose: string,
    durationMs: number = 60000,
  ): Promise<BrowserSessionLease> {
    const session = this.sessions.get(sessionId);
    if (!session) throw new Error(`Session ${sessionId} not found`);

    // Check for conflicting leases
    for (const lease of session.leases.values()) {
      if (lease.holderId !== holderId && lease.expiresAt > new Date()) {
        throw new Error(
          `Session ${sessionId} already leased to ${lease.holderId}`,
        );
      }
    }

    const leaseId = `lease_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    const now = new Date();
    const lease: BrowserSessionLease = {
      leaseId,
      sessionId,
      holderId,
      holderType,
      acquiredAt: now,
      expiresAt: new Date(now.getTime() + durationMs),
      purpose,
    };

    session.leases.set(leaseId, lease);
    session.config.lastActivityAt = new Date();

    logger.info("Session lease acquired", {
      sessionId,
      leaseId,
      holderId,
      holderType,
    });
    return lease;
  }

  async releaseLease(sessionId: string, leaseId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (session) {
      session.leases.delete(leaseId);
      logger.info("Session lease released", { sessionId, leaseId });
    }
  }

  async renewLease(
    sessionId: string,
    leaseId: string,
    durationMs: number = 60000,
  ): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) throw new Error(`Session ${sessionId} not found`);

    const lease = session.leases.get(leaseId);
    if (lease) {
      lease.expiresAt = new Date(Date.now() + durationMs);
    }
  }

  async getActiveLease(sessionId: string): Promise<BrowserSessionLease | null> {
    const session = this.sessions.get(sessionId);
    if (!session) return null;

    const now = new Date();
    for (const lease of session.leases.values()) {
      if (lease.expiresAt > now) {
        return lease;
      }
    }
    return null;
  }

  async updateActivity(sessionId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (session) {
      session.config.lastActivityAt = new Date();
      session.lastHeartbeat = new Date();
    }
  }

  async getSessionFingerprint(
    sessionId: string,
  ): Promise<BrowserStateFingerprint | null> {
    const session = this.sessions.get(sessionId);
    return session?.stateFingerprint || null;
  }

  async updateSessionFingerprint(
    sessionId: string,
    fingerprint: BrowserStateFingerprint,
  ): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (session) {
      session.stateFingerprint = fingerprint;
    }
  }

  async listSessions(filters?: {
    organizationId?: string;
    userId?: string;
    agentId?: string;
    status?: BrowserSessionStatus;
  }): Promise<BrowserSessionConfig[]> {
    let sessions = Array.from(this.sessions.values()).map((s) => s.config);

    if (filters) {
      if (filters.organizationId) {
        sessions = sessions.filter(
          (s) => s.organizationId === filters.organizationId,
        );
      }
      if (filters.userId) {
        sessions = sessions.filter((s) => s.userId === filters.userId);
      }
      if (filters.agentId) {
        sessions = sessions.filter((s) => s.agentId === filters.agentId);
      }
      if (filters.status) {
        sessions = sessions.filter((s) => s.status === filters.status);
      }
    }

    return sessions;
  }

  async getSessionCount(organizationId?: string): Promise<number> {
    if (organizationId) {
      return Array.from(this.sessions.values()).filter(
        (s) => s.config.organizationId === organizationId,
      ).length;
    }
    return this.sessions.size;
  }

  private async checkLimits(
    organizationId: string,
    userId?: string,
  ): Promise<void> {
    const orgCount = await this.getSessionCount(organizationId);
    if (orgCount >= this.config.maxSessionsPerOrganization) {
      throw new Error(
        `Organization session limit exceeded: ${this.config.maxSessionsPerOrganization}`,
      );
    }

    if (userId) {
      const userCount = Array.from(this.sessions.values()).filter(
        (s) => s.config.userId === userId,
      ).length;
      if (userCount >= this.config.maxSessionsPerUser) {
        throw new Error(
          `User session limit exceeded: ${this.config.maxSessionsPerUser}`,
        );
      }
    }

    if (this.sessions.size >= this.config.maxConcurrentSessions) {
      throw new Error(
        `Global session limit exceeded: ${this.config.maxConcurrentSessions}`,
      );
    }
  }

  private startCleanupTimer(): void {
    this.cleanupTimer = setInterval(async () => {
      await this.cleanupExpiredSessions();
    }, this.config.cleanupIntervalMs);
  }

  private startHeartbeatTimer(): void {
    this.heartbeatTimer = setInterval(async () => {
      await this.checkHeartbeats();
    }, this.config.heartbeatIntervalMs);
  }

  private async cleanupExpiredSessions(): Promise<void> {
    const now = new Date();
    const expiredSessions: string[] = [];

    for (const [sessionId, session] of this.sessions.entries()) {
      const expired = session.config.expiresAt < now;
      const idle =
        session.config.lastActivityAt.getTime() + this.config.idleTimeoutMs <
        now.getTime();

      if (expired || idle) {
        expiredSessions.push(sessionId);
      }
    }

    for (const sessionId of expiredSessions) {
      const session = this.sessions.get(sessionId);
      if (session) {
        session.config.status = expiredSessions.includes(sessionId)
          ? "EXPIRED"
          : "CLOSED";
        await this.closeSession(sessionId, true);
        logger.info("Session cleaned up", {
          sessionId,
          reason: expiredSessions.includes(sessionId) ? "expired" : "idle",
        });
      }
    }
  }

  private async checkHeartbeats(): Promise<void> {
    const now = new Date();
    const staleThreshold = this.config.heartbeatIntervalMs * 3;

    for (const [sessionId, session] of this.sessions.entries()) {
      if (now.getTime() - session.lastHeartbeat.getTime() > staleThreshold) {
        if (
          session.config.status === "READY" ||
          session.config.status === "BUSY"
        ) {
          logger.warn("Session heartbeat stale, marking as error", {
            sessionId,
          });
          session.config.status = "ERROR";
        }
      }
    }
  }

  async shutdown(): Promise<void> {
    if (this.cleanupTimer) clearInterval(this.cleanupTimer);
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);

    const sessionIds = Array.from(this.sessions.keys());
    await Promise.all(sessionIds.map((id) => this.closeSession(id, true)));

    logger.info("Browser session manager shut down");
  }
}

export const browserSessionManager = new BrowserSessionManager();
