import { initializeLogger } from '@openagent/logger';

// Runs before any test module is imported (module-level logger creation
// in source files requires an initialized logger at import time).
initializeLogger({ NODE_ENV: 'test', LOG_LEVEL: 'silent' } as never);
