import { createSDK } from '@openagent/sdk';

/**
 * TypeScript equivalent of pr_generation.py — review gate, commit,
 * approved push, PR draft (never auto-merged).
 */
async function main() {
  const sdk = createSDK({
    apiUrl: process.env.OPENAGENT_API_URL ?? 'http://localhost:8000',
    apiKey: process.env.OPENAGENT_API_KEY,
    organizationId: process.env.OPENAGENT_ORG_ID ?? '',
  });

  const taskId = process.env.OPENAGENT_TASK_ID ?? '';
  const diff = (await sdk.code.tasks.diff(taskId)) as { files?: unknown[] };
  if (!diff.files?.length) throw new Error('no changes to propose');

  const review = (await sdk.code.review({ task_id: taskId })) as {
    status: string;
    findings: Array<{ severity: string; finding: string }>;
  };
  const blocking = review.findings.filter((f) => f.severity === 'HIGH' || f.severity === 'CRITICAL');
  if (blocking.length > 0) {
    for (const f of blocking) console.log(`BLOCKED [${f.severity}] ${f.finding.slice(0, 160)}`);
    throw new Error('resolve blocking findings first');
  }

  const commit = (await sdk.code.tasks.commit(
    taskId,
    process.env.OPENAGENT_COMMIT_MESSAGE ?? 'fix: address review findings',
  )) as { revision?: string };
  console.log('commit:', commit.revision);

  await sdk.code.tasks.push(taskId, { approved: true });
  const pr = (await sdk.code.preparePR({
    task_id: taskId,
    title: process.env.OPENAGENT_PR_TITLE ?? 'Proposed changes',
    summary: process.env.OPENAGENT_PR_SUMMARY ?? '',
  })) as { id: string; status: string };
  console.log('pr:', pr.id, pr.status);
}

void main();
