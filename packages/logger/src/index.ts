import pino, { Level, LogDescriptor } from 'pino';
import { Env, isDevelopment } from '@openagent/config';
import { generateRequestId } from '@openagent/core';

export interface LogContext {
  request_id?: string;
  organization_id?: string;
  user_id?: string;
  [key: string]: unknown;
}

export interface OpenAgentLogger {
  debug(message: string, context?: LogContext): void;
  info(message: string, context?: LogContext): void;
  warn(message: string, context?: LogContext): void;
  error(message: string, context?: LogContext, error?: Error): void;
  fatal(message: string, context?: LogContext, error?: Error): void;
  child(context: LogContext): OpenAgentLogger;
  withRequestId(requestId?: string): OpenAgentLogger;
}

function createLogger(env: Env, baseContext: LogContext = {}): OpenAgentLogger {
  const isDev = isDevelopment(env);
  const level: Level = env.LOG_LEVEL;

  const pinoLogger = pino({
    level,
    transport: isDev
      ? {
          target: 'pino-pretty',
          options: {
            colorize: true,
            translateTime: 'SYS:standard',
            ignore: 'pid,hostname',
          },
        }
      : undefined,
    base: {
      service: 'openagent',
      env: env.OPENAGENT_ENV,
      ...baseContext,
    },
    formatters: {
      level: (label) => ({ level: label }),
    },
    timestamp: pino.stdTimeFunctions.isoTime,
    redact: {
      paths: [
        '*.password',
        '*.secret',
        '*.token',
        '*.api_key',
        '*.apiKey',
        '*.authorization',
        '*.credit_card',
        '*.ssn',
      ],
      censor: '[REDACTED]',
    },
  });

  function logWithContext(level: Level, message: string, context: LogContext = {}, error?: Error): void {
    const logContext: LogDescriptor = { ...baseContext, ...context };
    if (error) {
      logContext.err = {
        message: error.message,
        stack: error.stack,
        name: error.name,
      };
    }
    pinoLogger[level](logContext, message);
  }

  return {
    debug: (message, context) => logWithContext('debug', message, context),
    info: (message, context) => logWithContext('info', message, context),
    warn: (message, context) => logWithContext('warn', message, context),
    error: (message, context, error) => logWithContext('error', message, context, error),
    fatal: (message, context, error) => logWithContext('fatal', message, context, error),
    child: (context) => createLogger(env, { ...baseContext, ...context }),
    withRequestId: (requestId) => createLogger(env, { ...baseContext, request_id: requestId ?? generateRequestId() }),
  };
}

let globalLogger: OpenAgentLogger | null = null;

export function initializeLogger(env: Env): OpenAgentLogger {
  globalLogger = createLogger(env);
  return globalLogger;
}

export function getLogger(): OpenAgentLogger {
  if (!globalLogger) {
    throw new Error('Logger not initialized. Call initializeLogger first.');
  }
  return globalLogger;
}

export function createChildLogger(context: LogContext): OpenAgentLogger {
  return getLogger().child(context);
}

export function createRequestLogger(requestId?: string): OpenAgentLogger {
  return getLogger().withRequestId(requestId);
}