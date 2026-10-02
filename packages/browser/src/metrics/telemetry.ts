/** Tenant-aware browser telemetry (no private payload data in metric labels). */

export interface BrowserTelemetry {
  sessionsTotal: number;
  sessionsActive: number;
  tasksTotal: number;
  tasksSuccess: number;
  tasksFailed: number;
  crashesTotal: number;
  humanTakeovers: number;
  actionDurationMsTotal: number;
  navigationDurationMsTotal: number;
}

export const BROWSER_METRIC_NAMES = [
  'browser_sessions_total',
  'browser_sessions_active',
  'browser_tasks_total',
  'browser_tasks_success',
  'browser_tasks_failed',
  'browser_action_duration',
  'browser_navigation_duration',
  'browser_crashes',
  'browser_download_size',
  'browser_upload_size',
  'browser_wait_time',
  'browser_human_takeovers',
] as const;

export function emptyTelemetry(): BrowserTelemetry {
  return {
    sessionsTotal: 0,
    sessionsActive: 0,
    tasksTotal: 0,
    tasksSuccess: 0,
    tasksFailed: 0,
    crashesTotal: 0,
    humanTakeovers: 0,
    actionDurationMsTotal: 0,
    navigationDurationMsTotal: 0,
  };
}
