// Memory Package
// This package will contain the memory system (vector + relational)
// Implementation will be added in future phases

export const MEMORY_VERSION = '0.1.0';

export interface MemoryConfig {
  // Configuration for the memory system
}

export function createMemorySystem(_config: MemoryConfig) {
  return {
    async store(_input: unknown) {
      throw new Error('Not implemented - coming in future phase');
    },
    async retrieve(_input: unknown) {
      throw new Error('Not implemented - coming in future phase');
    },
  };
}