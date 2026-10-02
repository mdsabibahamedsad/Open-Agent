import {
  BrowserProviderConfig,
  BrowserProviderType,
  BrowserType,
  BrowserSessionConfig,
  BrowserContextConfig,
  BrowserScreenshotOptions,
  BrowserNavigateResult,
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

/** Page-function accepted by evaluate(): string expression or in-page function. */
export type PageFunction<T, A = any> = string | ((arg: A) => T | Promise<T>);

export interface BrowserProvider {
  readonly providerType: BrowserProviderType;

  launch(config: BrowserProviderConfig): Promise<BrowserInstance>;
  createContext(
    session: BrowserSessionConfig,
    contextConfig: BrowserContextConfig,
  ): Promise<BrowserContext>;
  close(): Promise<void>;
  connect?(endpoint: string): Promise<BrowserInstance>;
  healthCheck(): Promise<HealthCheckResult>;
}

export interface BrowserInstance {
  readonly instanceId: string;
  readonly providerType: BrowserProviderType;
  readonly browserType: BrowserType;
  readonly version: string;
  readonly isConnected: boolean;

  createContext(config: BrowserContextConfig): Promise<BrowserContext>;
  close(): Promise<void>;
  on(event: "disconnected", listener: () => void): this;
  on(event: string, listener: (...args: unknown[]) => void): this;
}

export interface BrowserContext {
  readonly contextId: string;
  readonly instanceId: string;
  readonly sessionId: string;

  newPage(): Promise<BrowserPage>;
  pages(): BrowserPage[];
  close(): Promise<void>;

  // Cookie management
  cookies(urls?: string[]): Promise<Cookie[]>;
  addCookies(cookies: Cookie[]): Promise<void>;
  clearCookies(): Promise<void>;

  // Storage
  storageState(): Promise<StorageState>;
  setStorageState(state: StorageState): Promise<void>;

  // Permissions
  grantPermissions(permissions: string[], origin?: string): Promise<void>;
  clearPermissions(): Promise<void>;

  // Offline
  setOffline(offline: boolean): Promise<void>;

  // Proxy
  setProxy(proxy: ProxyConfig): Promise<void>;

  // Geolocation
  setGeolocation(geolocation: Geolocation): Promise<void>;

  // Viewport
  setViewport(viewport: Viewport): Promise<void>;

  // User Agent
  setUserAgent(userAgent: string): Promise<void>;

  // Locale/Timezone
  setLocale(locale: string): Promise<void>;
  setTimezone(timezoneId: string): Promise<void>;

  on(event: "page", listener: (page: BrowserPage) => void): this;
  on(event: "close", listener: () => void): this;
  on(event: string, listener: (...args: unknown[]) => void): this;
}

export interface BrowserPage {
  readonly pageId: string;
  readonly contextId: string;
  readonly sessionId: string;
  url: string;
  title: string;
  status: "CREATED" | "LOADING" | "READY" | "CLOSED" | "ERROR";
  createdAt: Date;
  lastActivityAt: Date;
  isPopup?: boolean;
  openerPageId?: string;

  // Navigation
  goto(
    url: string,
    options?: {
      waitUntil?: "load" | "domcontentloaded" | "networkidle" | "commit";
      timeout?: number;
      referer?: string;
    },
  ): Promise<BrowserNavigateResult>;
  goBack(options?: {
    waitUntil?: "load" | "domcontentloaded" | "networkidle" | "commit";
    timeout?: number;
  }): Promise<BrowserNavigateResult | null>;
  goForward(options?: {
    waitUntil?: "load" | "domcontentloaded" | "networkidle" | "commit";
    timeout?: number;
  }): Promise<BrowserNavigateResult | null>;
  reload(options?: {
    waitUntil?: "load" | "domcontentloaded" | "networkidle" | "commit";
    timeout?: number;
  }): Promise<BrowserNavigateResult>;
  waitForURL(
    url: string | RegExp,
    options?: {
      timeout?: number;
      waitUntil?: "load" | "domcontentloaded" | "networkidle" | "commit";
    },
  ): Promise<void>;
  waitForLoadState(
    state: "load" | "domcontentloaded" | "networkidle",
    options?: { timeout?: number },
  ): Promise<void>;

  // Interaction
  click(
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
  ): Promise<void>;
  doubleClick(
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
  ): Promise<void>;
  type(
    selector: string,
    text: string,
    options?: { delay?: number; noWaitAfter?: boolean },
  ): Promise<void>;
  fill(
    selector: string,
    value: string,
    options?: { force?: boolean; noWaitAfter?: boolean; timeout?: number },
  ): Promise<void>;
  selectOption(
    selector: string,
    values: string | string[],
    options?: { noWaitAfter?: boolean; timeout?: number },
  ): Promise<string[]>;
  check(
    selector: string,
    options?: { force?: boolean; noWaitAfter?: boolean; timeout?: number },
  ): Promise<void>;
  uncheck(
    selector: string,
    options?: { force?: boolean; noWaitAfter?: boolean; timeout?: number },
  ): Promise<void>;
  hover(
    selector: string,
    options?: {
      force?: boolean;
      modifiers?: string[];
      position?: { x: number; y: number };
      timeout?: number;
      trial?: boolean;
    },
  ): Promise<void>;
  press(
    key: string,
    options?: { delay?: number; noWaitAfter?: boolean },
  ): Promise<void>;

  // Scroll
  scroll(options?: {
    x?: number;
    y?: number;
    behavior?: "auto" | "smooth" | "instant";
  }): Promise<void>;
  scrollIntoView(
    selector: string,
    options?: {
      behavior?: "auto" | "smooth" | "instant";
      block?: "start" | "center" | "end" | "nearest";
      inline?: "start" | "center" | "end" | "nearest";
    },
  ): Promise<void>;

  // Drag and Drop
  dragAndDrop(
    source: string,
    target: string,
    options?: {
      sourcePosition?: { x: number; y: number };
      targetPosition?: { x: number; y: number };
      force?: boolean;
      noWaitAfter?: boolean;
      timeout?: number;
    },
  ): Promise<void>;

  // Wait
  waitForSelector(
    selector: string,
    options?: {
      state?: "attached" | "detached" | "visible" | "hidden";
      timeout?: number;
      strict?: boolean;
    },
  ): Promise<BrowserElementHandle | null>;
  waitForFunction(
    expression: string,
    options?: { timeout?: number; polling?: "raf" | "mutation" | number },
  ): Promise<unknown>;
  waitForNavigation(options?: {
    url?: string | RegExp;
    waitUntil?: "load" | "domcontentloaded" | "networkidle" | "commit";
    timeout?: number;
  }): Promise<BrowserNavigateResult | null>;

  // Evaluation (accepts Playwright-style page functions or string expressions)
  evaluate<T>(pageFunction: PageFunction<T>, arg?: unknown): Promise<T>;
  evaluateHandle(
    pageFunction: PageFunction<unknown>,
    arg?: unknown,
  ): Promise<BrowserElementHandle>;

  // Screenshots
  screenshot(options?: BrowserScreenshotOptions): Promise<Buffer>;

  // Extraction
  extract(
    selector: string,
    attribute?: string,
    multiple?: boolean,
  ): Promise<string | string[] | null>;
  extractAll(selector: string): Promise<Record<string, unknown>[]>;

  // Forms
  setInputFiles(selector: string, files: BrowserUploadFile[]): Promise<void>;

  // Downloads
  download(
    selector: string,
    options?: BrowserDownloadOptions,
  ): Promise<BrowserDownload>;
  expectDownload(options?: BrowserDownloadOptions): Promise<BrowserDownload>;

  // Frames
  mainFrame(): BrowserFrame;
  frames(): BrowserFrame[];
  frame(name: string): BrowserFrame | null;
  frameByUrl(url: string | RegExp): BrowserFrame | null;

  // Dialogs
  onDialog(handler: (dialog: BrowserDialog) => void): void;
  waitForDialog(options?: { timeout?: number }): Promise<BrowserDialog>;

  // Cookies
  cookies(urls?: string[]): Promise<Cookie[]>;

  // Viewport
  setViewport(viewport: Viewport): Promise<void>;
  viewport(): Viewport | null;

  // Accessibility
  accessibility(): AccessibilityTree;

  // Focus
  focus(selector: string): Promise<void>;
  blur(selector: string): Promise<void>;

  // Close
  close(options?: { runBeforeUnload?: boolean }): Promise<void>;

  // Page events
  on(event: "close", listener: () => void): this;
  on(event: "crash", listener: () => void): this;
  on(event: "download", listener: (download: BrowserDownload) => void): this;
  on(event: "popup", listener: (page: BrowserPage) => void): this;
  on(event: "framenavigated", listener: (frame: BrowserFrame) => void): this;
  on(event: "load", listener: () => void): this;
  on(event: "domcontentloaded", listener: () => void): this;
  on(event: string, listener: (...args: unknown[]) => void): this;
}

export interface BrowserFrame {
  readonly frameId: string;
  readonly pageId: string;
  readonly parentFrameId?: string;
  url: string;
  name?: string;
  isMainFrame: boolean;

  // Same methods as page but scoped to frame
  click(
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
  ): Promise<void>;
  type(
    selector: string,
    text: string,
    options?: { delay?: number; noWaitAfter?: boolean },
  ): Promise<void>;
  fill(
    selector: string,
    value: string,
    options?: { force?: boolean; noWaitAfter?: boolean; timeout?: number },
  ): Promise<void>;
  selectOption(
    selector: string,
    values: string | string[],
    options?: { noWaitAfter?: boolean; timeout?: number },
  ): Promise<string[]>;
  waitForSelector(
    selector: string,
    options?: {
      state?: "attached" | "detached" | "visible" | "hidden";
      timeout?: number;
      strict?: boolean;
    },
  ): Promise<BrowserElementHandle | null>;
  evaluate<T>(pageFunction: PageFunction<T>, arg?: unknown): Promise<T>;
  evaluateHandle(
    pageFunction: PageFunction<unknown>,
    arg?: unknown,
  ): Promise<BrowserElementHandle>;
  content(): Promise<string>;
}

export interface BrowserDialog {
  readonly type: "alert" | "confirm" | "prompt" | "beforeunload";
  readonly message: string;
  readonly defaultValue?: string;

  accept(promptText?: string): Promise<void>;
  dismiss(): Promise<void>;
}

export interface BrowserDownload {
  readonly downloadId: string;
  readonly url: string;
  readonly suggestedFilename: string;
  readonly pageId: string;

  path(): Promise<string | null>;
  saveAs(path: string): Promise<void>;
  cancel(): Promise<void>;
  failure(): Promise<string | null>;
  delete(): Promise<void>;
}

export interface BrowserElementHandle {
  readonly elementId: string;
  readonly pageId: string;
  readonly frameId?: string;
  readonly selector: string;

  click(options?: {
    button?: "left" | "right" | "middle";
    clickCount?: number;
    delay?: number;
    modifiers?: string[];
    position?: { x: number; y: number };
    force?: boolean;
    noWaitAfter?: boolean;
    trial?: boolean;
  }): Promise<void>;
  type(
    text: string,
    options?: { delay?: number; noWaitAfter?: boolean },
  ): Promise<void>;
  fill(
    value: string,
    options?: { force?: boolean; noWaitAfter?: boolean; timeout?: number },
  ): Promise<void>;
  hover(options?: {
    force?: boolean;
    modifiers?: string[];
    position?: { x: number; y: number };
    timeout?: number;
    trial?: boolean;
  }): Promise<void>;
  press(
    key: string,
    options?: { delay?: number; noWaitAfter?: boolean },
  ): Promise<void>;
  selectOption(
    values: string | string[],
    options?: { noWaitAfter?: boolean; timeout?: number },
  ): Promise<string[]>;
  boundingBox(): Promise<BoundingBox | null>;
  screenshot(options?: BrowserScreenshotOptions): Promise<Buffer>;
  evaluate<T>(pageFunction: PageFunction<T>, arg?: unknown): Promise<T>;
  getAttribute(name: string): Promise<string | null>;
  innerText(): Promise<string>;
  innerHTML(): Promise<string>;
  isVisible(): Promise<boolean>;
  isEnabled(): Promise<boolean>;
  isChecked(): Promise<boolean>;
  isHidden(): Promise<boolean>;
  isEditable(): Promise<boolean>;
  dispatchEvent(
    type: string,
    eventInit?: Record<string, unknown>,
  ): Promise<void>;
}

export interface AccessibilityTree {
  snapshot(options?: {
    interestingOnly?: boolean;
    root?: BrowserElementHandle;
  }): Promise<AccessibilityNode>;
}

export interface HealthCheckResult {
  status: "HEALTHY" | "DEGRADED" | "UNAVAILABLE";
  latencyMs: number;
  details?: Record<string, unknown>;
}

export interface BrowserProviderFactory {
  create(config: BrowserProviderConfig): Promise<BrowserProvider>;
  readonly supportedTypes: BrowserProviderType[];
}

export class BrowserProviderRegistry {
  private providers: Map<BrowserProviderType, BrowserProviderFactory> =
    new Map();

  register(factory: BrowserProviderFactory): void {
    for (const type of factory.supportedTypes) {
      this.providers.set(type, factory);
    }
  }

  get(type: BrowserProviderType): BrowserProviderFactory | undefined {
    return this.providers.get(type);
  }

  async create(
    type: BrowserProviderType,
    config: BrowserProviderConfig,
  ): Promise<BrowserProvider> {
    const factory = this.providers.get(type);
    if (!factory) {
      throw new Error(`Browser provider type '${type}' not registered`);
    }
    return factory.create(config);
  }

  list(): BrowserProviderType[] {
    return Array.from(this.providers.keys());
  }
}

export const browserProviderRegistry = new BrowserProviderRegistry();
