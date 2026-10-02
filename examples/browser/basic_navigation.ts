import { createBrowserSession } from '@openagent/browser';

/**
 * TypeScript equivalent of basic_navigation.py — same canonical API,
 * same policy gates. Auth via API key + X-Organization-ID header.
 */
async function main() {
  const session = await createBrowserSession({
    baseUrl: process.env.OPENAGENT_API_URL ?? 'http://localhost:8000',
    apiKey: process.env.OPENAGENT_API_KEY,
    organizationId: process.env.OPENAGENT_ORG_ID ?? '',
  });
  console.log('session:', session.sessionId);

  await session.navigate('https://example.com');
  const data = await session.extract('body');
  console.log('extracted:', JSON.stringify(data).slice(0, 300));

  await session.close();
}

void main();
