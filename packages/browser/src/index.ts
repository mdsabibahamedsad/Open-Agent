// OpenAgent Browser Engine — canonical entry point.
// Provider-neutral orchestration over Playwright/Chromium; policy-aware via Tool Runtime.
export const BROWSER_VERSION = "0.1.0";

export * from "./core/types";
export * from "./providers/types";
export * from "./providers/playwright";
export * from "./session/manager";
export * from "./tasks/manager";
export * from "./actions/executors";
export * from "./extraction/dom";
export * from "./security/url-validator";
export * from "./security/hardening";
export * from "./observation/compression";
export * from "./artifacts/store";
export * from "./research/service";
export * from "./vision/providers";
export * from "./metrics/telemetry";
export * from "./api/tool-adapter";
export * from "./sdk/client";
