import { createSDK } from '@openagent/sdk';

/**
 * TypeScript equivalent of simple_fix.py — same canonical API, same policy
 * gates. Auth via API key + organization id.
 */
async function main() {
  const sdk = createSDK({
    apiUrl: process.env.OPENAGENT_API_URL ?? 'http://localhost:8000',
    apiKey: process.env.OPENAGENT_API_KEY,
    organizationId: process.env.OPENAGENT_ORG_ID ?? '',
  });

  const repositoryId = process.env.OPENAGENT_REPOSITORY_ID ?? '';
  const task = (await sdk.code.tasks.create({
    repository_id: repositoryId,
    objective: 'Fix the off-by-one error in session expiry validation',
    max_steps: 25,
  })) as { id: string; task_id: string; status: string };
  console.log('task:', task.task_id, task.status);

  const final = (await sdk.code.tasks.wait(task.id, { timeoutMs: 20 * 60 * 1000 })) as {
    status: string;
    current_step: number;
    max_steps: number;
  };
  console.log('final:', final.status, `step ${final.current_step}/${final.max_steps}`);

  const { diff } = (await sdk.code.tasks.result(task.id)) as {
    diff: { files?: Array<{ path: string; additions: number; deletions: number }> };
  };
  for (const f of diff.files ?? []) {
    console.log(' -', f.path, `+${f.additions}/-${f.deletions}`);
  }
}

void main();
