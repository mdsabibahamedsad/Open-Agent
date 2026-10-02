export function assert(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

export function unreachable(value: never, message: string): never {
  throw new Error(`${message}: ${JSON.stringify(value)}`);
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function retry<T>(
  fn: () => Promise<T>,
  options: { attempts: number; delay: number; backoff?: number } = {
    attempts: 3,
    delay: 1000,
  },
): Promise<T> {
  const { attempts, delay, backoff = 2 } = options;
  return fn().catch((error) => {
    if (attempts <= 1) throw error;
    return sleep(delay).then(() =>
      retry(fn, { attempts: attempts - 1, delay: delay * backoff, backoff }),
    );
  });
}

export function omit<T extends Record<string, unknown>, K extends keyof T>(
  obj: T,
  keys: K[],
): Omit<T, K> {
  const result = { ...obj };
  for (const key of keys) {
    delete result[key];
  }
  return result;
}

export function pick<T extends Record<string, unknown>, K extends keyof T>(
  obj: T,
  keys: K[],
): Pick<T, K> {
  const result = {} as Pick<T, K>;
  for (const key of keys) {
    if (key in obj) {
      result[key] = obj[key];
    }
  }
  return result;
}

export function deepEqual<T>(a: T, b: T): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function generateRequestId(): string {
  return `req_${crypto.randomUUID()}`;
}

export function generateId(prefix: string): string {
  return `${prefix}_${crypto.randomUUID()}`;
}
