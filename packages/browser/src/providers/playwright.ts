import {
  BrowserProvider,
  BrowserInstance,
  BrowserContext,
  BrowserPage,
  BrowserFrame,
  BrowserDialog,
  BrowserDownload,
  BrowserElementHandle,
  AccessibilityTree,
  HealthCheckResult,
  PageFunction,
} from "./types";
import {
  BrowserProviderConfig,
  BrowserProviderType,
  BrowserType,
  BrowserSessionConfig,
  BrowserContextConfig,
  BrowserNavigateResult,
  BrowserScreenshotOptions,
  BrowserUploadFile,
  BrowserDownloadOptions,
  Cookie,
  Viewport,
  Geolocation,
  ProxyConfig,
  StorageState,
  BoundingBox,
  AccessibilityNode,
} from "../core/types";
import type * as playwright from "playwright";

export class PlaywrightBrowserProvider implements BrowserProvider {
  readonly providerType: BrowserProviderType = "playwright";
  private browser: playwright.Browser | null = null;
  private browserType: BrowserType = "chromium";
  private config: BrowserProviderConfig | null = null;
  private launchOptions: playwright.LaunchOptions = {};

  /** Lazy-load Playwright so the package imports cleanly without the driver installed. */
  private async loadPlaywright(): Promise<typeof import("playwright")> {
    try {
      return await Function('return import("playwright")')();
    } catch {
      throw new Error(
        'Playwright is not installed. Install the "playwright" package and run `playwright install chromium` to drive real browsers.',
      );
    }
  }

  async launch(config: BrowserProviderConfig): Promise<BrowserInstance> {
    this.config = config;
    this.browserType = config.browserType || "chromium";

    this.launchOptions = {
      headless: config.headless ?? true,
      executablePath: config.executablePath,
      args: config.args,
      env: config.env,
      timeout: config.timeout ?? 30000,
      slowMo: config.slowMo,
    };

    const pw = await this.loadPlaywright();
    const browserType = pw[this.browserType];
    if (!browserType) {
      throw new Error(`Unsupported browser type: ${this.browserType}`);
    }

    this.browser = await (browserType as playwright.BrowserType).launch(
      this.launchOptions,
    );

    return new PlaywrightBrowserInstance(
      this.browser,
      this.browserType,
      this.config,
    );
  }

  async createContext(
    session: BrowserSessionConfig,
    contextConfig: BrowserContextConfig,
  ): Promise<BrowserContext> {
    if (!this.browser) {
      throw new Error("Browser not launched. Call launch() first.");
    }

    const context = await this.browser.newContext({
      storageState: contextConfig.storageState as never,
      viewport: contextConfig.viewport,
      userAgent: contextConfig.userAgent,
      locale: contextConfig.locale,
      timezoneId: contextConfig.timezoneId,
      geolocation: contextConfig.geolocation,
      permissions: contextConfig.permissions,
      proxy: contextConfig.proxy
        ? {
            server: contextConfig.proxy.server,
            username: contextConfig.proxy.username,
            password: contextConfig.proxy.password,
            bypass: contextConfig.proxy.bypass,
          }
        : undefined,
      offline: contextConfig.offline,
      httpCredentials: undefined,
      recordVideo: undefined,
      recordHar: undefined,
    });

    return new PlaywrightBrowserContext(
      context,
      contextConfig.contextId,
      session.sessionId,
    );
  }

  async close(): Promise<void> {
    if (this.browser) {
      await this.browser.close();
      this.browser = null;
    }
  }

  async connect(endpoint: string): Promise<BrowserInstance> {
    const pw = await this.loadPlaywright();
    this.browser = await pw.chromium.connectOverCDP(endpoint);
    return new PlaywrightBrowserInstance(
      this.browser,
      this.browserType,
      this.config!,
    );
  }

  async healthCheck(): Promise<HealthCheckResult> {
    const start = Date.now();
    try {
      if (!this.browser || !this.browser.isConnected()) {
        return { status: "UNAVAILABLE", latencyMs: Date.now() - start };
      }

      const context = await this.browser.newContext();
      const page = await context.newPage();
      await page.goto("about:blank");
      await page.close();
      await context.close();

      return { status: "HEALTHY", latencyMs: Date.now() - start };
    } catch (error) {
      return {
        status: "UNAVAILABLE",
        latencyMs: Date.now() - start,
        details: { error: String(error) },
      };
    }
  }
}

class PlaywrightBrowserInstance implements BrowserInstance {
  readonly instanceId: string;
  readonly providerType: BrowserProviderType = "playwright";
  readonly browserType: BrowserType;
  readonly version: string;
  readonly isConnected: boolean;

  private browser: playwright.Browser;
  private config: BrowserProviderConfig;

  constructor(
    browser: playwright.Browser,
    browserType: BrowserType,
    config: BrowserProviderConfig,
  ) {
    this.browser = browser;
    this.browserType = browserType;
    this.config = config;
    this.instanceId = `browser_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    this.version = browser.version();
    this.isConnected = browser.isConnected();
  }

  async createContext(config: BrowserContextConfig): Promise<BrowserContext> {
    const context = await this.browser.newContext({
      storageState: config.storageState as never,
      viewport: config.viewport,
      userAgent: config.userAgent,
      locale: config.locale,
      timezoneId: config.timezoneId,
      geolocation: config.geolocation,
      permissions: config.permissions,
      proxy: config.proxy
        ? {
            server: config.proxy.server,
            username: config.proxy.username,
            password: config.proxy.password,
            bypass: config.proxy.bypass,
          }
        : undefined,
      offline: config.offline,
    });

    return new PlaywrightBrowserContext(
      context,
      config.contextId,
      config.sessionId,
    );
  }

  async close(): Promise<void> {
    await this.browser.close();
  }

  on(event: "disconnected", listener: () => void): this;
  on(event: string, listener: (...args: unknown[]) => void): this;
  on(event: string, listener: (...args: unknown[]) => void): this {
    (
      this.browser as unknown as {
        on: (e: string, l: (...a: never[]) => void) => void;
      }
    ).on(event, listener as (...args: never[]) => void);
    return this;
  }
}

class PlaywrightBrowserContext implements BrowserContext {
  readonly contextId: string;
  readonly instanceId: string;
  readonly sessionId: string;
  private context: playwright.BrowserContext;
  private pageMap: Map<string, PlaywrightBrowserPage> = new Map();

  constructor(
    context: playwright.BrowserContext,
    contextId: string,
    sessionId: string,
  ) {
    this.context = context;
    this.contextId = contextId;
    this.instanceId = `instance_${contextId}`;
    this.sessionId = sessionId;
  }

  async newPage(): Promise<BrowserPage> {
    const page = await this.context.newPage();
    const pageId = `page_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    const wrapper = new PlaywrightBrowserPage(
      page,
      this.contextId,
      this.sessionId,
      pageId,
    );
    this.pageMap.set(pageId, wrapper);
    return wrapper;
  }

  pages(): BrowserPage[] {
    return Array.from(this.pageMap.values());
  }

  async close(): Promise<void> {
    for (const page of this.pageMap.values()) {
      await page.close();
    }
    this.pageMap.clear();
    await this.context.close();
  }

  async cookies(urls?: string[]): Promise<Cookie[]> {
    const cookies = await this.context.cookies(urls);
    return cookies.map((c) => ({
      name: c.name,
      value: c.value,
      domain: c.domain,
      path: c.path,
      expires: c.expires,
      httpOnly: c.httpOnly,
      secure: c.secure,
      sameSite: c.sameSite as "Strict" | "Lax" | "None" | undefined,
    }));
  }

  async addCookies(cookies: Cookie[]): Promise<void> {
    await this.context.addCookies(cookies as playwright.Cookie[]);
  }

  async clearCookies(): Promise<void> {
    await this.context.clearCookies();
  }

  async storageState(): Promise<StorageState> {
    const state = await this.context.storageState();
    return {
      cookies: state.cookies.map((c) => ({
        name: c.name,
        value: c.value,
        domain: c.domain,
        path: c.path,
        expires: c.expires,
        httpOnly: c.httpOnly,
        secure: c.secure,
        sameSite: c.sameSite as "Strict" | "Lax" | "None" | undefined,
      })),
      origins: state.origins.map((o) => {
        const ls = o.localStorage as unknown as
          Array<{ name: string; value: string }> | Record<string, string>;
        return {
          origin: o.origin,
          localStorage: Array.isArray(ls)
            ? Object.fromEntries(ls.map(({ name, value }) => [name, value]))
            : { ...ls },
        };
      }),
    };
  }

  async setStorageState(state: StorageState): Promise<void> {
    // Playwright only accepts storage state at context creation; apply best-effort
    // to the live context: cookies directly, localStorage via init script for
    // subsequently created pages.
    if (state.cookies.length > 0) {
      await this.context.addCookies(state.cookies as never);
    }
    for (const origin of state.origins) {
      const entries = Object.entries(origin.localStorage);
      if (entries.length === 0) continue;
      await this.context.addInitScript(
        `([origin, entries]) => {
          if (window.location.origin !== origin) return;
          for (const [k, v] of entries) {
            try { window.localStorage.setItem(k, v); } catch { /* ignore */ }
          }
        }`,
        [origin.origin, entries],
      );
    }
  }

  async grantPermissions(
    permissions: string[],
    origin?: string,
  ): Promise<void> {
    await this.context.grantPermissions(
      permissions as never,
      origin ? { origin } : undefined,
    );
  }

  async clearPermissions(): Promise<void> {
    await this.context.clearPermissions();
  }

  async setOffline(offline: boolean): Promise<void> {
    await this.context.setOffline(offline);
  }

  async setProxy(_proxy: ProxyConfig): Promise<void> {
    // Playwright cannot change proxy on a live context; fail loud so callers
    // recreate the context instead of silently running with the old proxy.
    throw new Error(
      "setProxy requires creating a new browser context with the proxy configured",
    );
  }

  async setGeolocation(geolocation: Geolocation): Promise<void> {
    await this.context.setGeolocation({
      latitude: geolocation.latitude,
      longitude: geolocation.longitude,
      accuracy: geolocation.accuracy,
    });
  }

  async setViewport(viewport: Viewport): Promise<void> {
    for (const p of this.context.pages()) {
      await p.setViewportSize({
        width: viewport.width,
        height: viewport.height,
      });
    }
  }

  async setUserAgent(userAgent: string): Promise<void> {
    // No post-creation user-agent API on BrowserContext; propagate via headers
    // (network effect) — full navigator.userAgent override requires a new context.
    await this.context.setExtraHTTPHeaders({ "User-Agent": userAgent });
  }

  async setLocale(_locale: string): Promise<void> {
    throw new Error(
      "setLocale requires creating a new browser context with the locale configured",
    );
  }

  async setTimezone(_timezoneId: string): Promise<void> {
    throw new Error(
      "setTimezone requires creating a new browser context with the timezone configured",
    );
  }

  on(event: "page", listener: (page: BrowserPage) => void): this;
  on(event: "close", listener: () => void): this;
  on(event: string, listener: (...args: unknown[]) => void): this;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  on(event: string, listener: (...args: any[]) => void): this {
    if (event === "page") {
      const pageListener = listener as (page: BrowserPage) => void;
      this.context.on("page", (p: playwright.Page) => {
        const pageId = `page_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        const wrapper = new PlaywrightBrowserPage(
          p,
          this.contextId,
          this.sessionId,
          pageId,
        );
        this.pageMap.set(pageId, wrapper);
        pageListener(wrapper);
      });
      return this;
    }
    (
      this.context as unknown as {
        on: (e: string, l: (...a: never[]) => void) => void;
      }
    ).on(event, listener as (...args: never[]) => void);
    return this;
  }
}

class PlaywrightBrowserPage implements BrowserPage {
  readonly pageId: string;
  readonly contextId: string;
  readonly sessionId: string;
  url: string = "about:blank";
  title: string = "";
  status: "CREATED" | "LOADING" | "READY" | "CLOSED" | "ERROR" = "CREATED";
  readonly createdAt: Date = new Date();
  lastActivityAt: Date = new Date();
  isPopup: boolean = false;
  openerPageId?: string;

  private page: playwright.Page;
  private frameCache: Map<string, PlaywrightBrowserFrame> = new Map();

  constructor(
    page: playwright.Page,
    contextId: string,
    sessionId: string,
    pageId: string,
  ) {
    this.page = page;
    this.contextId = contextId;
    this.sessionId = sessionId;
    this.pageId = pageId;

    this.setupEventListeners();
  }

  private setupEventListeners(): void {
    this.page.on("framenavigated", (frame) => {
      this.url = frame.url();
      this.lastActivityAt = new Date();
    });

    this.page.on("load", () => {
      this.status = "READY";
      this.lastActivityAt = new Date();
    });

    this.page.on("domcontentloaded", () => {
      this.status = "READY";
      this.lastActivityAt = new Date();
    });

    this.page.on("close", () => {
      this.status = "CLOSED";
    });

    this.page.on("crash", () => {
      this.status = "ERROR";
    });

    this.page.on("popup", (popup) => {
      const pageId = `page_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      const wrapper = new PlaywrightBrowserPage(
        popup,
        this.contextId,
        this.sessionId,
        pageId,
      );
      wrapper.isPopup = true;
      wrapper.openerPageId = this.pageId;
      this.frameCache.clear();
    });
  }

  async goto(
    url: string,
    options?: {
      waitUntil?: "load" | "domcontentloaded" | "networkidle" | "commit";
      timeout?: number;
      referer?: string;
    },
  ): Promise<BrowserNavigateResult> {
    this.status = "LOADING";
    const start = Date.now();

    const response = await this.page.goto(url, {
      waitUntil: options?.waitUntil || "networkidle",
      timeout: options?.timeout ?? 30000,
      referer: options?.referer,
    });

    this.url = this.page.url();
    this.title = await this.page.title();
    this.status = "READY";
    this.lastActivityAt = new Date();

    return {
      url: this.url,
      title: this.title,
      status: response?.status() ?? 0,
      loadTime: Date.now() - start,
    };
  }

  async goBack(options?: {
    waitUntil?: "load" | "domcontentloaded" | "networkidle" | "commit";
    timeout?: number;
  }): Promise<BrowserNavigateResult | null> {
    const response = await this.page.goBack({
      waitUntil: options?.waitUntil || "networkidle",
      timeout: options?.timeout ?? 30000,
    });

    if (!response) return null;

    this.url = this.page.url();
    this.title = await this.page.title();
    this.lastActivityAt = new Date();

    return {
      url: this.url,
      title: this.title,
      status: response.status(),
      loadTime: 0,
    };
  }

  async goForward(options?: {
    waitUntil?: "load" | "domcontentloaded" | "networkidle" | "commit";
    timeout?: number;
  }): Promise<BrowserNavigateResult | null> {
    const response = await this.page.goForward({
      waitUntil: options?.waitUntil || "networkidle",
      timeout: options?.timeout ?? 30000,
    });

    if (!response) return null;

    this.url = this.page.url();
    this.title = await this.page.title();
    this.lastActivityAt = new Date();

    return {
      url: this.url,
      title: this.title,
      status: response.status(),
      loadTime: 0,
    };
  }

  async reload(options?: {
    waitUntil?: "load" | "domcontentloaded" | "networkidle" | "commit";
    timeout?: number;
  }): Promise<BrowserNavigateResult> {
    const start = Date.now();
    const response = await this.page.reload({
      waitUntil: options?.waitUntil || "networkidle",
      timeout: options?.timeout ?? 30000,
    });

    this.url = this.page.url();
    this.title = await this.page.title();
    this.lastActivityAt = new Date();

    return {
      url: this.url,
      title: this.title,
      status: response?.status() ?? 0,
      loadTime: Date.now() - start,
    };
  }

  async waitForURL(
    url: string | RegExp,
    options?: {
      timeout?: number;
      waitUntil?: "load" | "domcontentloaded" | "networkidle" | "commit";
    },
  ): Promise<void> {
    await this.page.waitForURL(url, {
      timeout: options?.timeout ?? 30000,
      waitUntil: options?.waitUntil || "networkidle",
    });
    this.url = this.page.url();
    this.lastActivityAt = new Date();
  }

  async waitForLoadState(
    state: "load" | "domcontentloaded" | "networkidle",
    options?: { timeout?: number },
  ): Promise<void> {
    await this.page.waitForLoadState(state, {
      timeout: options?.timeout ?? 30000,
    });
    this.lastActivityAt = new Date();
  }

  async click(
    selector: string,
    options?: {
      button?: "left" | "right" | "middle";
      clickCount?: number;
      delay?: number;
      modifiers?: string[];
      position?: { x: number; y: number };
      force?: boolean;
      noWaitAfter?: boolean;
      trial?: boolean;
    },
  ): Promise<void> {
    await this.page.click(selector, {
      button: options?.button || "left",
      clickCount: options?.clickCount || 1,
      delay: options?.delay,
      modifiers: options?.modifiers as never,
      position: options?.position,
      force: options?.force,
      noWaitAfter: options?.noWaitAfter,
      trial: options?.trial,
      timeout: 30000,
    });
    this.lastActivityAt = new Date();
  }

  async doubleClick(
    selector: string,
    options?: {
      button?: "left" | "right" | "middle";
      delay?: number;
      modifiers?: string[];
      position?: { x: number; y: number };
      force?: boolean;
      noWaitAfter?: boolean;
      trial?: boolean;
    },
  ): Promise<void> {
    await this.page.dblclick(selector, {
      button: options?.button || "left",
      delay: options?.delay,
      modifiers: options?.modifiers as never,
      position: options?.position,
      force: options?.force,
      noWaitAfter: options?.noWaitAfter,
      trial: options?.trial,
      timeout: 30000,
    });
    this.lastActivityAt = new Date();
  }

  async type(
    selector: string,
    text: string,
    options?: { delay?: number; noWaitAfter?: boolean },
  ): Promise<void> {
    await this.page.type(selector, text, {
      delay: options?.delay,
      noWaitAfter: options?.noWaitAfter,
      timeout: 30000,
    });
    this.lastActivityAt = new Date();
  }

  async fill(
    selector: string,
    value: string,
    options?: { force?: boolean; noWaitAfter?: boolean; timeout?: number },
  ): Promise<void> {
    await this.page.fill(selector, value, {
      force: options?.force,
      noWaitAfter: options?.noWaitAfter,
      timeout: options?.timeout ?? 30000,
    });
    this.lastActivityAt = new Date();
  }

  async selectOption(
    selector: string,
    values: string | string[],
    options?: { noWaitAfter?: boolean; timeout?: number },
  ): Promise<string[]> {
    const result = await this.page.selectOption(selector, values, {
      noWaitAfter: options?.noWaitAfter,
      timeout: options?.timeout ?? 30000,
    });
    this.lastActivityAt = new Date();
    return result;
  }

  async check(
    selector: string,
    options?: { force?: boolean; noWaitAfter?: boolean; timeout?: number },
  ): Promise<void> {
    await this.page.check(selector, {
      force: options?.force,
      noWaitAfter: options?.noWaitAfter,
      timeout: options?.timeout ?? 30000,
    });
    this.lastActivityAt = new Date();
  }

  async uncheck(
    selector: string,
    options?: { force?: boolean; noWaitAfter?: boolean; timeout?: number },
  ): Promise<void> {
    await this.page.uncheck(selector, {
      force: options?.force,
      noWaitAfter: options?.noWaitAfter,
      timeout: options?.timeout ?? 30000,
    });
    this.lastActivityAt = new Date();
  }

  async hover(
    selector: string,
    options?: {
      force?: boolean;
      modifiers?: string[];
      position?: { x: number; y: number };
      timeout?: number;
      trial?: boolean;
    },
  ): Promise<void> {
    await this.page.hover(selector, {
      force: options?.force,
      modifiers: options?.modifiers as never,
      position: options?.position,
      timeout: options?.timeout ?? 30000,
      trial: options?.trial,
    });
    this.lastActivityAt = new Date();
  }

  async press(
    key: string,
    options?: { delay?: number; noWaitAfter?: boolean },
  ): Promise<void> {
    await this.page.keyboard.press(key, {
      delay: options?.delay,
    });
    this.lastActivityAt = new Date();
  }

  async scroll(options?: {
    x?: number;
    y?: number;
    behavior?: "auto" | "smooth" | "instant";
  }): Promise<void> {
    const { x = 0, y = 0, behavior = "auto" } = options ?? {};
    await this.page.evaluate(
      ([left, top, beh]: [number, number, ScrollBehavior]) => {
        window.scrollTo({ left, top, behavior: beh });
      },
      [x, y, behavior] as [number, number, ScrollBehavior],
    );
    this.lastActivityAt = new Date();
  }

  async scrollIntoView(
    selector: string,
    options?: {
      behavior?: "auto" | "smooth" | "instant";
      block?: "start" | "center" | "end" | "nearest";
      inline?: "start" | "center" | "end" | "nearest";
    },
  ): Promise<void> {
    const arg: [string, ScrollIntoViewOptions] = [
      selector,
      {
        behavior: options?.behavior,
        block: options?.block,
        inline: options?.inline,
      },
    ];
    await this.page.evaluate(([sel, opts]) => {
      document.querySelector(sel)?.scrollIntoView(opts);
    }, arg);
    this.lastActivityAt = new Date();
  }

  async dragAndDrop(
    source: string,
    target: string,
    options?: {
      sourcePosition?: { x: number; y: number };
      targetPosition?: { x: number; y: number };
      force?: boolean;
      noWaitAfter?: boolean;
      timeout?: number;
    },
  ): Promise<void> {
    await this.page.dragAndDrop(source, target, {
      sourcePosition: options?.sourcePosition,
      targetPosition: options?.targetPosition,
      force: options?.force,
      noWaitAfter: options?.noWaitAfter,
      timeout: options?.timeout ?? 30000,
    });
    this.lastActivityAt = new Date();
  }

  async waitForSelector(
    selector: string,
    options?: {
      state?: "attached" | "detached" | "visible" | "hidden";
      timeout?: number;
      strict?: boolean;
    },
  ): Promise<BrowserElementHandle | null> {
    const element = await this.page.waitForSelector(selector, {
      state: options?.state || "visible",
      timeout: options?.timeout ?? 30000,
      strict: options?.strict,
    });

    if (!element) return null;

    const elementId = `element_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    return new PlaywrightBrowserElementHandle(
      element,
      this.pageId,
      elementId,
      selector,
    );
  }

  async waitForFunction(
    expression: string,
    options?: { timeout?: number; polling?: "raf" | "mutation" | number },
  ): Promise<unknown> {
    // Playwright supports 'raf' | number polling; 'mutation' falls back to default polling.
    const polling =
      options?.polling === "mutation" ? undefined : options?.polling;
    return this.page.waitForFunction(expression, undefined, {
      timeout: options?.timeout ?? 30000,
      polling,
    });
  }

  async waitForNavigation(options?: {
    url?: string | RegExp;
    waitUntil?: "load" | "domcontentloaded" | "networkidle" | "commit";
    timeout?: number;
  }): Promise<BrowserNavigateResult | null> {
    const response = await this.page.waitForNavigation({
      url: options?.url,
      waitUntil: options?.waitUntil || "networkidle",
      timeout: options?.timeout ?? 30000,
    });

    if (!response) return null;

    this.url = this.page.url();
    this.title = await this.page.title();
    this.lastActivityAt = new Date();

    return {
      url: this.url,
      title: this.title,
      status: response.status(),
      loadTime: 0,
    };
  }

  async evaluate<T>(pageFunction: PageFunction<T>, arg?: unknown): Promise<T> {
    return this.page.evaluate(pageFunction as never, arg);
  }

  async evaluateHandle(
    pageFunction: PageFunction<unknown>,
    arg?: unknown,
  ): Promise<BrowserElementHandle> {
    const handle = await this.page.evaluateHandle(pageFunction as never, arg);
    const elementId = `element_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    return new PlaywrightBrowserElementHandle(
      handle.asElement()!,
      this.pageId,
      elementId,
      "",
    );
  }

  async screenshot(options?: BrowserScreenshotOptions): Promise<Buffer> {
    const buffer = await this.page.screenshot({
      fullPage: options?.fullPage ?? false,
      type: options?.format || "png",
      quality: options?.quality,
      clip: options?.clip,
      omitBackground: options?.omitBackground,
      animations: options?.animations,
      caret: options?.caret,
      scale: options?.scale,
      timeout: options?.timeout ?? 30000,
    });
    return Buffer.from(buffer);
  }

  async extract(
    selector: string,
    attribute?: string,
    multiple?: boolean,
  ): Promise<string | string[] | null> {
    if (multiple) {
      const elements = await this.page.$$(selector);
      if (!elements.length) return [];

      const results: string[] = [];
      for (const element of elements) {
        if (attribute) {
          const value = await element.getAttribute(attribute);
          results.push(value || "");
        } else {
          const text = await element.innerText();
          results.push(text);
        }
      }
      return results;
    }

    const element = await this.page.$(selector);
    if (!element) return null;

    if (attribute) {
      return element.getAttribute(attribute) || null;
    }
    return element.innerText();
  }

  async extractAll(selector: string): Promise<Record<string, unknown>[]> {
    return this.page.evaluate((sel) => {
      const elements = document.querySelectorAll(sel);
      return Array.from(elements).map((el) => {
        const obj: Record<string, unknown> = {};
        for (const attr of el.attributes) {
          obj[attr.name] = attr.value;
        }
        obj.innerText = el.textContent;
        obj.innerHTML = el.innerHTML;
        obj.tagName = el.tagName;
        return obj;
      });
    }, selector);
  }

  async setInputFiles(
    selector: string,
    files: BrowserUploadFile[],
  ): Promise<void> {
    const filePaths = files.map((f) => {
      // In a real implementation, we'd write the buffer to a temp file
      // For now, we'll use a data URL approach or temp file
      return f.name;
    });

    await this.page.setInputFiles(selector, filePaths);
    this.lastActivityAt = new Date();
  }

  async download(
    selector: string,
    options?: BrowserDownloadOptions,
  ): Promise<BrowserDownload> {
    const [download] = await Promise.all([
      this.page.waitForEvent("download", {
        timeout: options?.timeout ?? 30000,
      }),
      this.page.click(selector),
    ]);

    return new PlaywrightBrowserDownload(download, this.pageId);
  }

  async expectDownload(
    options?: BrowserDownloadOptions,
  ): Promise<BrowserDownload> {
    const download = await this.page.waitForEvent("download", {
      timeout: options?.timeout ?? 30000,
    });
    return new PlaywrightBrowserDownload(download, this.pageId);
  }

  mainFrame(): BrowserFrame {
    const frame = this.page.mainFrame();
    const frameId = `frame_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    return new PlaywrightBrowserFrame(frame, this.pageId, frameId, true);
  }

  frames(): BrowserFrame[] {
    return this.page.frames().map((f) => {
      const frameId = `frame_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      return new PlaywrightBrowserFrame(
        f,
        this.pageId,
        frameId,
        f === this.page.mainFrame(),
      );
    });
  }

  frame(name: string): BrowserFrame | null {
    const frame = this.page.frame(name);
    if (!frame) return null;
    const frameId = `frame_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    return new PlaywrightBrowserFrame(
      frame,
      this.pageId,
      frameId,
      frame === this.page.mainFrame(),
    );
  }

  frameByUrl(url: string | RegExp): BrowserFrame | null {
    const frame = this.page.frames().find((f) => {
      if (typeof url === "string") return f.url() === url;
      return url.test(f.url());
    });
    if (!frame) return null;
    const frameId = `frame_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    return new PlaywrightBrowserFrame(
      frame,
      this.pageId,
      frameId,
      frame === this.page.mainFrame(),
    );
  }

  onDialog(handler: (dialog: BrowserDialog) => void): void {
    this.page.on("dialog", (dialog) => {
      handler(new PlaywrightBrowserDialog(dialog));
    });
  }

  async waitForDialog(options?: { timeout?: number }): Promise<BrowserDialog> {
    const dialog = await this.page.waitForEvent("dialog", {
      timeout: options?.timeout ?? 30000,
    });
    return new PlaywrightBrowserDialog(dialog);
  }

  async cookies(urls?: string[]): Promise<Cookie[]> {
    return this.context.cookies(urls);
  }

  async setViewport(viewport: Viewport): Promise<void> {
    await this.page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    });
  }

  viewport(): Viewport | null {
    const vp = this.page.viewportSize();
    return vp ? { width: vp.width, height: vp.height } : null;
  }

  accessibility(): AccessibilityTree {
    return new PlaywrightAccessibilityTree(this.page);
  }

  async focus(selector: string): Promise<void> {
    await this.page.focus(selector);
    this.lastActivityAt = new Date();
  }

  async blur(selector: string): Promise<void> {
    await this.page.locator(selector).blur();
    this.lastActivityAt = new Date();
  }

  async close(options?: { runBeforeUnload?: boolean }): Promise<void> {
    await this.page.close({ runBeforeUnload: options?.runBeforeUnload });
    this.status = "CLOSED";
  }

  on(event: "close", listener: () => void): this;
  on(event: "crash", listener: () => void): this;
  on(event: "download", listener: (download: BrowserDownload) => void): this;
  on(event: "popup", listener: (page: BrowserPage) => void): this;
  on(event: "framenavigated", listener: (frame: BrowserFrame) => void): this;
  on(event: "load", listener: () => void): this;
  on(event: "domcontentloaded", listener: () => void): this;
  on(event: string, listener: (...args: unknown[]) => void): this;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  on(event: string, listener: (...args: any[]) => void): this {
    if (event === "download") {
      const downloadListener = listener as (download: BrowserDownload) => void;
      this.page.on("download", (d: playwright.Download) =>
        downloadListener(new PlaywrightBrowserDownload(d, this.pageId)),
      );
      return this;
    }
    if (event === "popup") {
      const popupListener = listener as (page: BrowserPage) => void;
      this.page.on("popup", (p: playwright.Page) => {
        const pageId = `page_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        const wrapper = new PlaywrightBrowserPage(
          p,
          this.contextId,
          this.sessionId,
          pageId,
        );
        wrapper.isPopup = true;
        wrapper.openerPageId = this.pageId;
        popupListener(wrapper);
      });
      return this;
    }
    if (event === "framenavigated") {
      const frameListener = listener as (frame: BrowserFrame) => void;
      this.page.on("framenavigated", (f: playwright.Frame) => {
        const frameId = `frame_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        frameListener(
          new PlaywrightBrowserFrame(
            f,
            this.pageId,
            frameId,
            f === this.page.mainFrame(),
          ),
        );
      });
      return this;
    }
    (
      this.page as unknown as {
        on: (e: string, l: (...a: never[]) => void) => void;
      }
    ).on(event, listener as (...args: never[]) => void);
    return this;
  }

  private get context(): playwright.BrowserContext {
    return this.page.context();
  }
}

class PlaywrightBrowserFrame implements BrowserFrame {
  readonly frameId: string;
  readonly pageId: string;
  readonly parentFrameId?: string;
  url: string;
  name?: string;
  readonly isMainFrame: boolean;
  private frame: playwright.Frame;

  constructor(
    frame: playwright.Frame,
    pageId: string,
    frameId: string,
    isMainFrame: boolean,
  ) {
    this.frame = frame;
    this.pageId = pageId;
    this.frameId = frameId;
    this.url = frame.url();
    this.name = frame.name() || undefined;
    this.isMainFrame = isMainFrame;
    this.parentFrameId = frame.parentFrame()
      ? `frame_${frame.parentFrame()!.url()}`
      : undefined;
  }

  async click(
    selector: string,
    options?: {
      button?: "left" | "right" | "middle";
      clickCount?: number;
      delay?: number;
      modifiers?: string[];
      position?: { x: number; y: number };
      force?: boolean;
      noWaitAfter?: boolean;
      trial?: boolean;
    },
  ): Promise<void> {
    await this.frame.click(selector, options as any);
  }

  async type(
    selector: string,
    text: string,
    options?: { delay?: number; noWaitAfter?: boolean },
  ): Promise<void> {
    await this.frame.type(selector, text, options as any);
  }

  async fill(
    selector: string,
    value: string,
    options?: { force?: boolean; noWaitAfter?: boolean; timeout?: number },
  ): Promise<void> {
    await this.frame.fill(selector, value, options as any);
  }

  async selectOption(
    selector: string,
    values: string | string[],
    options?: { noWaitAfter?: boolean; timeout?: number },
  ): Promise<string[]> {
    return this.frame.selectOption(selector, values, options as any);
  }

  async waitForSelector(
    selector: string,
    options?: {
      state?: "attached" | "detached" | "visible" | "hidden";
      timeout?: number;
      strict?: boolean;
    },
  ): Promise<BrowserElementHandle | null> {
    const element = await this.frame.waitForSelector(selector, options as any);
    if (!element) return null;
    const elementId = `element_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    return new PlaywrightBrowserElementHandle(
      element,
      this.pageId,
      elementId,
      selector,
      this.frameId,
    );
  }

  async evaluate<T>(pageFunction: PageFunction<T>, arg?: unknown): Promise<T> {
    return this.frame.evaluate(pageFunction as never, arg);
  }

  async evaluateHandle(
    pageFunction: PageFunction<unknown>,
    arg?: unknown,
  ): Promise<BrowserElementHandle> {
    const handle = await this.frame.evaluateHandle(pageFunction as never, arg);
    const elementId = `element_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    return new PlaywrightBrowserElementHandle(
      handle.asElement()!,
      this.pageId,
      elementId,
      "",
      this.frameId,
    );
  }

  async content(): Promise<string> {
    return this.frame.content();
  }
}

class PlaywrightBrowserDialog implements BrowserDialog {
  readonly type: "alert" | "confirm" | "prompt" | "beforeunload";
  readonly message: string;
  readonly defaultValue?: string;
  private dialog: playwright.Dialog;

  constructor(dialog: playwright.Dialog) {
    this.dialog = dialog;
    this.type = dialog.type() as any;
    this.message = dialog.message();
    this.defaultValue = dialog.defaultValue();
  }

  async accept(promptText?: string): Promise<void> {
    await this.dialog.accept(promptText);
  }

  async dismiss(): Promise<void> {
    await this.dialog.dismiss();
  }
}

class PlaywrightBrowserDownload implements BrowserDownload {
  readonly downloadId: string;
  readonly url: string;
  readonly suggestedFilename: string;
  readonly pageId: string;
  private download: playwright.Download;

  constructor(download: playwright.Download, pageId: string) {
    this.download = download;
    this.pageId = pageId;
    this.downloadId = `download_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    this.url = download.url();
    this.suggestedFilename = download.suggestedFilename();
  }

  async path(): Promise<string | null> {
    return this.download.path();
  }

  async saveAs(path: string): Promise<void> {
    await this.download.saveAs(path);
  }

  async cancel(): Promise<void> {
    await this.download.cancel();
  }

  async failure(): Promise<string | null> {
    return this.download.failure();
  }

  async delete(): Promise<void> {
    await this.download.delete();
  }
}

class PlaywrightBrowserElementHandle implements BrowserElementHandle {
  readonly elementId: string;
  readonly pageId: string;
  readonly frameId?: string;
  readonly selector: string;
  private element: playwright.ElementHandle;

  constructor(
    element: playwright.ElementHandle,
    pageId: string,
    elementId: string,
    selector: string,
    frameId?: string,
  ) {
    this.element = element;
    this.pageId = pageId;
    this.elementId = elementId;
    this.selector = selector;
    this.frameId = frameId;
  }

  async click(options?: {
    button?: "left" | "right" | "middle";
    clickCount?: number;
    delay?: number;
    modifiers?: string[];
    position?: { x: number; y: number };
    force?: boolean;
    noWaitAfter?: boolean;
    trial?: boolean;
  }): Promise<void> {
    await this.element.click(options as any);
  }

  async type(
    text: string,
    options?: { delay?: number; noWaitAfter?: boolean },
  ): Promise<void> {
    await this.element.type(text, options as any);
  }

  async fill(
    value: string,
    options?: { force?: boolean; noWaitAfter?: boolean; timeout?: number },
  ): Promise<void> {
    await this.element.fill(value, options as any);
  }

  async hover(options?: {
    force?: boolean;
    modifiers?: string[];
    position?: { x: number; y: number };
    timeout?: number;
    trial?: boolean;
  }): Promise<void> {
    await this.element.hover(options as any);
  }

  async press(
    key: string,
    options?: { delay?: number; noWaitAfter?: boolean },
  ): Promise<void> {
    await this.element.press(key, options as any);
  }

  async selectOption(
    values: string | string[],
    options?: { noWaitAfter?: boolean; timeout?: number },
  ): Promise<string[]> {
    return this.element.selectOption(values, options as any);
  }

  async boundingBox(): Promise<BoundingBox | null> {
    const box = await this.element.boundingBox();
    return box
      ? { x: box.x, y: box.y, width: box.width, height: box.height }
      : null;
  }

  async screenshot(options?: BrowserScreenshotOptions): Promise<Buffer> {
    const buffer = await this.element.screenshot(options as any);
    return Buffer.from(buffer);
  }

  async evaluate<T>(pageFunction: PageFunction<T>, arg?: unknown): Promise<T> {
    return this.element.evaluate(pageFunction as never, arg);
  }

  async getAttribute(name: string): Promise<string | null> {
    return this.element.getAttribute(name);
  }

  async innerText(): Promise<string> {
    return this.element.innerText();
  }

  async innerHTML(): Promise<string> {
    return this.element.innerHTML();
  }

  async isVisible(): Promise<boolean> {
    return this.element.isVisible();
  }

  async isEnabled(): Promise<boolean> {
    return this.element.isEnabled();
  }

  async isChecked(): Promise<boolean> {
    return this.element.isChecked();
  }

  async isHidden(): Promise<boolean> {
    return this.element.isHidden();
  }

  async isEditable(): Promise<boolean> {
    return this.element.isEditable();
  }

  async dispatchEvent(
    type: string,
    eventInit?: Record<string, unknown>,
  ): Promise<void> {
    await this.element.dispatchEvent(type, eventInit);
  }
}

class PlaywrightAccessibilityTree implements AccessibilityTree {
  private page: playwright.Page;

  constructor(page: playwright.Page) {
    this.page = page;
  }

  async snapshot(options?: {
    interestingOnly?: boolean;
    root?: BrowserElementHandle;
  }): Promise<AccessibilityNode> {
    // Implemented over CDP Accessibility.getFullAXTree (works regardless of
    // high-level Playwright helper availability).
    const session = await this.page.context().newCDPSession(this.page);
    try {
      const raw = (await session.send("Accessibility.getFullAXTree", {
        interestingOnly: options?.interestingOnly ?? true,
      } as never)) as unknown as { nodes: CdpAXNode[] };
      const byId = new Map<string, CdpAXNode>();
      for (const n of raw.nodes) byId.set(n.nodeId, n);
      const convert = (id: string): AccessibilityNode | null => {
        const n = byId.get(id);
        if (!n || n.ignored) return null;
        const kids: AccessibilityNode[] = [];
        for (const childId of n.childIds ?? []) {
          const c = convert(childId);
          if (c) kids.push(c);
        }
        return {
          role: n.role?.value ?? "generic",
          name: strProp(n, "name"),
          value: strProp(n, "value"),
          description: strProp(n, "description"),
          children: kids.length > 0 ? kids : undefined,
        };
      };
      const parentIds = new Set<string>();
      for (const m of raw.nodes)
        for (const c of m.childIds ?? []) parentIds.add(c);
      const roots = raw.nodes.filter((n) => !parentIds.has(n.nodeId));
      const children = roots
        .map((r) => convert(r.nodeId))
        .filter((x): x is AccessibilityNode => x !== null);
      return {
        role: "RootWebArea",
        children: children.length > 0 ? children : undefined,
      };
    } finally {
      await session.detach().catch(() => undefined);
    }
  }
}

interface CdpAXNode {
  nodeId: string;
  ignored?: boolean;
  role?: { value?: string };
  name?: { value?: string };
  value?: { value?: string | number };
  description?: { value?: string };
  childIds?: string[];
}

function strProp(
  n: CdpAXNode,
  key: "name" | "value" | "description",
): string | undefined {
  const v = n[key]?.value;
  return v === undefined || v === null ? undefined : String(v);
}

export class PlaywrightProviderFactory {
  readonly supportedTypes: BrowserProviderType[] = ["playwright"];

  async create(config: BrowserProviderConfig): Promise<BrowserProvider> {
    const provider = new PlaywrightBrowserProvider();
    await provider.launch(config);
    return provider;
  }
}

import { browserProviderRegistry } from "./types";
browserProviderRegistry.register(new PlaywrightProviderFactory());
