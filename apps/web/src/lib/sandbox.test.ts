import {
  decisionSummary,
  formatBytes,
  formatDuration,
  isTerminalExecutionStatus,
  normalizeExecutionStatus,
  riskTone,
} from './sandbox';

describe('sandbox lib helpers', () => {
  it('normalizes WAITING to WAITING_FOR_APPROVAL', () => {
    expect(normalizeExecutionStatus('WAITING')).toBe('WAITING_FOR_APPROVAL');
    expect(normalizeExecutionStatus('SUCCEEDED')).toBe('SUCCEEDED');
  });

  it('classifies terminal states', () => {
    for (const s of ['SUCCEEDED', 'FAILED', 'TIMED_OUT', 'POLICY_DENIED', 'WAITING_FOR_APPROVAL']) {
      expect(isTerminalExecutionStatus(s)).toBe(true);
    }
    expect(isTerminalExecutionStatus('RUNNING')).toBe(false);
    expect(isTerminalExecutionStatus('QUEUED')).toBe(false);
  });

  it('maps risk to tones', () => {
    expect(riskTone('LOW')).toBe('ok');
    expect(riskTone('MEDIUM')).toBe('warn');
    expect(riskTone('HIGH')).toBe('bad');
    expect(riskTone('CRITICAL')).toBe('critical');
  });

  it('formats bytes and durations', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(undefined)).toBe('—');
    expect(formatDuration(500)).toBe('500 ms');
    expect(formatDuration(1500)).toBe('1.5 s');
    expect(formatDuration(null)).toBe('—');
  });

  it('summarizes policy decisions without secrets', () => {
    const allowed = decisionSummary({
      status: 'SUCCEEDED',
      risk_level: 'MEDIUM',
      policy_decision: { network: 'NO_NETWORK', filesystem: 'WORKSPACE_RW' },
    });
    expect(allowed).toContain('ALLOWED');
    expect(allowed).toContain('NO_NETWORK');
    const denied = decisionSummary({ status: 'POLICY_DENIED', risk_level: 'HIGH', policy_decision: {} });
    expect(denied).toContain('DENIED');
    const parked = decisionSummary({ status: 'WAITING_FOR_APPROVAL', risk_level: 'HIGH' });
    expect(parked).toContain('APPROVAL');
  });
});
