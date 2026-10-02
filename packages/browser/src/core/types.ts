import { JSONSchema } from '@openagent/types';

export type BrowserProviderType = 'playwright' | 'browserless' | 'remote-chromium' | 'cloud-browser' | 'custom';

export type BrowserType = 'chromium' | 'firefox' | 'webkit';

export type BrowserSessionStatus = 
  | 'CREATED'
  | 'STARTING'
  | 'READY'
  | 'BUSY'
  | 'WAITING'
  | 'PAUSED'
  | 'ERROR'
  | 'CLOSING'
  | 'CLOSED'
  | 'EXPIRED';

export type BrowserProfileType = 'EPHEMERAL' | 'PERSISTENT' | 'SHARED' | 'ORGANIZATION' | 'USER';

export type BrowserPageStatus = 'CREATED' | 'LOADING' | 'READY' | 'CLOSED' | 'ERROR';

export type BrowserActionType = 
  | 'NAVIGATE'
  | 'CLICK'
  | 'DOUBLE_CLICK'
  | 'TYPE'
  | 'FILL'
  | 'SELECT'
  | 'CHECK'
  | 'UNCHECK'
  | 'HOVER'
  | 'SCROLL'
  | 'PRESS_KEY'
  | 'DRAG'
  | 'DROP'
  | 'WAIT'
  | 'SCREENSHOT'
  | 'EXTRACT'
  | 'UPLOAD'
  | 'DOWNLOAD'
  | 'SWITCH_TAB'
  | 'GO_BACK'
  | 'GO_FORWARD'
  | 'RELOAD'
  | 'FOCUS'
  | 'EVALUATE'
  | 'SET_VIEWPORT'
  | 'SET_COOKIE'
  | 'CLEAR_COOKIES'
  | 'GET_COOKIES'
  | 'AUTHENTICATE'
  | 'HANDLE_DIALOG'
  | 'WAIT_FOR_SELECTOR'
  | 'WAIT_FOR_NAVIGATION'
  | 'WAIT_FOR_FUNCTION'
  | 'SELECT_OPTION'
  | 'SET_INPUT_FILES'
  | 'CHECKBOX'
  | 'RADIO';

export type BrowserActionRiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export type BrowserTaskStatus = 
  | 'QUEUED'
  | 'STARTING'
  | 'RUNNING'
  | 'WAITING'
  | 'WAITING_FOR_HUMAN'
  | 'PAUSED'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'CANCELLED'
  | 'TIMED_OUT';

export type BrowserDomainPolicyAction = 'ALLOW' | 'DENY' | 'CONFIRM';

export type BrowserObservationStrategy = 'minimal' | 'standard' | 'detailed' | 'visual' | 'custom';

export type BrowserChallengeType = 'CAPTCHA' | 'MFA_REQUIRED' | 'LOGIN_REQUIRED' | 'SECURITY_CHECK' | 'BOT_CHALLENGE';

export interface BrowserProviderConfig {
  type: BrowserProviderType;
  browserType?: BrowserType;
  headless?: boolean;
  executablePath?: string;
  args?: string[];
  env?: Record<string, string>;
  timeout?: number;
  slowMo?: number;
  viewport?: Viewport;
  userAgent?: string;
  locale?: string;
  timezoneId?: string;
  geolocation?: Geolocation;
  permissions?: string[];
  offline?: boolean;
  proxy?: ProxyConfig;
  downloadsPath?: string;
  recordVideo?: VideoConfig;
  recordHar?: HarConfig;
}

export interface Viewport {
  width: number;
  height: number;
  deviceScaleFactor?: number;
  isMobile?: boolean;
  hasTouch?: boolean;
  isLandscape?: boolean;
}

export interface Geolocation {
  latitude: number;
  longitude: number;
  accuracy?: number;
}

export interface ProxyConfig {
  server: string;
  username?: string;
  password?: string;
  bypass?: string;
}

export interface VideoConfig {
  dir: string;
  size?: Viewport;
}

export interface HarConfig {
  path: string;
  omitContent?: boolean;
}

export interface BrowserSessionConfig {
  sessionId: string;
  organizationId: string;
  userId?: string;
  agentId?: string;
  workflowExecutionId?: string;
  browserProfileId?: string;
  provider: BrowserProviderConfig;
  status: BrowserSessionStatus;
  createdAt: Date;
  lastActivityAt: Date;
  expiresAt: Date;
  headless: boolean;
  metadata: Record<string, unknown>;
}

export interface BrowserContextConfig {
  contextId: string;
  sessionId: string;
  cookies?: Cookie[];
  localStorage?: Record<string, string>;
  sessionStorage?: Record<string, string>;
  permissions?: string[];
  locale?: string;
  timezoneId?: string;
  viewport?: Viewport;
  userAgent?: string;
  geolocation?: Geolocation;
  proxy?: ProxyConfig;
  offline?: boolean;
  storageState?: StorageState;
}

export interface StorageState {
  cookies: Cookie[];
  origins: OriginStorage[];
}

export interface OriginStorage {
  origin: string;
  localStorage: Record<string, string>;
}

export interface Cookie {
  name: string;
  value: string;
  domain: string;
  path: string;
  expires?: number;
  httpOnly?: boolean;
  secure?: boolean;
  sameSite?: 'Strict' | 'Lax' | 'None';
}

export interface BrowserProfile {
  profileId: string;
  organizationId: string;
  ownerId: string;
  displayName: string;
  browserType: BrowserType;
  profileType: BrowserProfileType;
  storageState?: StorageState;
  policy: BrowserProfilePolicy;
  createdAt: Date;
  updatedAt: Date;
  lastUsedAt?: Date;
}

export interface BrowserProfilePolicy {
  allowedDomains?: string[];
  blockedDomains?: string[];
  maxPages?: number;
  maxDownloads?: number;
  downloadPath?: string;
  allowJavaScript?: boolean;
  allowPlugins?: boolean;
  allowPopups?: boolean;
  allowFileAccess?: boolean;
  defaultViewport?: Viewport;
  defaultUserAgent?: string;
  credentials?: BrowserCredentialRef[];
}

export interface BrowserCredentialRef {
  id: string;
  type: 'username_password' | 'oauth' | 'api_key' | 'cookie' | 'custom';
  reference: string;
  domain?: string;
}

export interface BrowserAction {
  id: string;
  taskId: string;
  sessionId: string;
  pageId: string;
  type: BrowserActionType;
  input: Record<string, unknown>;
  riskLevel: BrowserActionRiskLevel;
  status: 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED' | 'WAITING_APPROVAL';
  result?: BrowserActionResult;
  error?: BrowserActionError;
  startedAt?: Date;
  completedAt?: Date;
  durationMs?: number;
  retryCount: number;
  idempotencyKey?: string;
}

export interface BrowserActionResult {
  success: boolean;
  output?: Record<string, unknown>;
  artifacts?: BrowserArtifactRef[];
  observations?: BrowserObservation;
  error?: BrowserActionError;
}

export interface BrowserActionError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  retryable: boolean;
}

export interface BrowserObservation {
  url: string;
  title: string;
  viewport: Viewport;
  scrollPosition: { x: number; y: number };
  interactiveElements: InteractiveElement[];
  textContent?: string;
  domSnapshot?: string;
  screenshot?: string;
  accessibilityTree?: AccessibilityNode;
  metadata: Record<string, unknown>;
}

export interface InteractiveElement {
  id: string;
  role: string;
  name?: string;
  description?: string;
  visible: boolean;
  enabled: boolean;
  selected?: boolean;
  checked?: boolean;
  level?: number;
  boundingBox?: BoundingBox;
  selector?: string;
  attributes?: Record<string, string>;
  children?: InteractiveElement[];
}

export interface AccessibilityNode {
  role: string;
  name?: string;
  value?: string;
  description?: string;
  states?: string[];
  children?: AccessibilityNode[];
}

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface BrowserTask {
  taskId: string;
  organizationId: string;
  agentId?: string;
  workflowExecutionId?: string;
  browserSessionId: string;
  status: BrowserTaskStatus;
  objective: string;
  currentUrl?: string;
  currentPageId?: string;
  currentStep: number;
  maxSteps: number;
  timeout: number;
  riskPolicy: BrowserTaskRiskPolicy;
  createdAt: Date;
  updatedAt: Date;
  completedAt?: Date;
  metadata: Record<string, unknown>;
}

export interface BrowserTaskRiskPolicy {
  allowedRiskLevels: BrowserActionRiskLevel[];
  maxRiskLevel: BrowserActionRiskLevel;
  requireApprovalFor: BrowserActionRiskLevel[];
  blockedActions: BrowserActionType[];
}

export interface BrowserArtifactRef {
  artifactId: string;
  type: 'screenshot' | 'download' | 'extraction' | 'html' | 'har' | 'video' | 'trace';
  name: string;
  size: number;
  mimeType: string;
  storageRef: string;
  createdAt: Date;
  expiresAt?: Date;
  metadata?: Record<string, unknown>;
}

export interface BrowserArtifact {
  artifactId: string;
  organizationId: string;
  taskId?: string;
  sessionId?: string;
  type: 'screenshot' | 'download' | 'extraction' | 'html' | 'har' | 'video' | 'trace';
  name: string;
  size: number;
  mimeType: string;
  storageRef: string;
  metadata: Record<string, unknown>;
  createdAt: Date;
  expiresAt?: Date;
}

export interface BrowserEvent {
  eventId: string;
  type: BrowserEventType;
  organizationId: string;
  sessionId?: string;
  taskId?: string;
  pageId?: string;
  timestamp: Date;
  payload: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export type BrowserEventType =
  | 'browser.session.created'
  | 'browser.session.ready'
  | 'browser.session.closed'
  | 'browser.session.crashed'
  | 'browser.session.expired'
  | 'browser.navigation.started'
  | 'browser.navigation.completed'
  | 'browser.navigation.failed'
  | 'browser.action.started'
  | 'browser.action.completed'
  | 'browser.action.failed'
  | 'browser.page.created'
  | 'browser.page.closed'
  | 'browser.page.crashed'
  | 'browser.download.started'
  | 'browser.download.completed'
  | 'browser.download.failed'
  | 'browser.upload.started'
  | 'browser.upload.completed'
  | 'browser.upload.failed'
  | 'browser.challenge.detected'
  | 'browser.human_required'
  | 'browser.profile.accessed'
  | 'browser.credential.used'
  | 'browser.policy.denied'
  | 'browser.artifact.created'
  | 'browser.state.changed';

export interface BrowserMetrics {
  sessionsTotal: number;
  sessionsActive: number;
  tasksTotal: number;
  tasksSuccess: number;
  tasksFailed: number;
  actionDurationMs: number;
  navigationDurationMs: number;
  crashesTotal: number;
  downloadSizeBytes: number;
  uploadSizeBytes: number;
  waitTimeMs: number;
  humanTakeovers: number;
}

export interface BrowserDomainPolicy {
  id: string;
  organizationId?: string;
  teamId?: string;
  userId?: string;
  agentId?: string;
  workflowId?: string;
  browserProfileId?: string;
  taskId?: string;
  domain: string;
  action: BrowserDomainPolicyAction;
  priority: number;
  reason?: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface BrowserNavigationOptions {
  waitUntil?: 'load' | 'domcontentloaded' | 'networkidle' | 'commit';
  timeout?: number;
  referer?: string;
}

export interface BrowserClickOptions {
  button?: 'left' | 'right' | 'middle';
  clickCount?: number;
  delay?: number;
  modifiers?: string[];
  position?: { x: number; y: number };
  force?: boolean;
  noWaitAfter?: boolean;
  trial?: boolean;
}

export interface BrowserTypeOptions {
  delay?: number;
  noWaitAfter?: boolean;
}

export interface BrowserScrollOptions {
  x?: number;
  y?: number;
  behavior?: 'auto' | 'smooth' | 'instant';
}

export interface BrowserWaitOptions {
  state?: 'attached' | 'detached' | 'visible' | 'hidden';
  timeout?: number;
}

export interface BrowserScreenshotOptions {
  fullPage?: boolean;
  format?: 'png' | 'jpeg';
  quality?: number;
  clip?: BoundingBox;
  omitBackground?: boolean;
  animations?: 'allow' | 'disabled';
  caret?: 'hide' | 'initial';
  scale?: 'css' | 'device';
  timeout?: number;
}

export interface BrowserExtractOptions {
  selector: string;
  attribute?: string;
  multiple?: boolean;
}

export interface BrowserUploadOptions {
  selector: string;
  files: BrowserUploadFile[];
  noWaitAfter?: boolean;
}

export interface BrowserUploadFile {
  name: string;
  mimeType: string;
  buffer: Buffer | Uint8Array;
}

export interface BrowserDownloadOptions {
  path?: string;
  timeout?: number;
  suggestedFilename?: string;
}

export interface BrowserNavigateResult {
  url: string;
  title: string;
  status: number;
  loadTime: number;
}

export interface BrowserCredentialResolution {
  username?: string;
  password?: string;
  token?: string;
  cookies?: Cookie[];
  headers?: Record<string, string>;
}

export interface BrowserSessionLease {
  leaseId: string;
  sessionId: string;
  holderId: string;
  holderType: 'agent' | 'workflow' | 'human';
  acquiredAt: Date;
  expiresAt: Date;
  purpose: string;
}

export interface BrowserStateFingerprint {
  url: string;
  title: string;
  textHash: string;
  domHash: string;
  interactiveElementsHash: string;
  timestamp: Date;
}