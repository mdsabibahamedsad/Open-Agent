import path from 'node:path';
import { defineConfig } from 'vitest/config';

// Workspace packages only emit CJS (dist/index.js) while their exports maps
// also advertise ESM (dist/index.mjs); alias to TypeScript sources for tests.
export default defineConfig({
  test: {
    setupFiles: ['./src/test-setup.ts'],
  },
  resolve: {
    alias: ['logger', 'tool-system', 'types', 'config', 'core'].map((pkg) => ({
      find: new RegExp(`^@openagent/${pkg}$`),
      replacement: path.resolve(__dirname, `../${pkg}/src/index.ts`),
    })),
  },
});
