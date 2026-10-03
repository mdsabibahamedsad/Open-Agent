import { initializeLogger } from "@openagent/logger";
import type { Env } from "@openagent/config";

// Vitest setup: tool-system modules create child loggers at import time,
// so the global logger must exist before any test module is evaluated.
const env: Env = {
  OPENAGENT_ENV: "development",
  LOG_LEVEL: "error",
  API_URL: "http://localhost:8000",
  WEB_URL: "http://localhost:3000",
  DATABASE_URL: "sqlite://:memory:",
  REDIS_URL: "redis://localhost:6379",
  SECRET_KEY: "test-secret-key-00000000000000000000",
  ENCRYPTION_KEY: "test-encryption-key-0000000000000000",
  CORS_ORIGINS: "http://localhost:3000",
};

initializeLogger(env);
