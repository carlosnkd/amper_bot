import { MemoryRateLimitStore } from '../../src/ratelimit/memoryStore';
import { RateLimitStore } from '../../src/ratelimit/store';
import { createRateLimitStore } from '../../src/ratelimit/storeFactory';

export interface StoreCandidate {
  name: 'memory' | 'redis';
  create: () => RateLimitStore;
}

/**
 * The integration suite runs against every available store. Memory is always
 * available; Redis is included only when REDIS_URL is set (see docker-compose)
 * and is skipped at runtime if the server cannot actually be reached.
 */
export function storeCandidates(): StoreCandidate[] {
  const candidates: StoreCandidate[] = [
    { name: 'memory', create: () => new MemoryRateLimitStore() },
  ];

  const redisUrl = process.env.REDIS_URL;
  if (redisUrl) {
    candidates.push({
      name: 'redis',
      create: () => createRateLimitStore({ redisUrl }),
    });
  }

  return candidates;
}

/** True when the store answers a probe increment. */
export async function isStoreReachable(store: RateLimitStore): Promise<boolean> {
  try {
    await store.increment(`probe:${Date.now()}`, 1000);
    return true;
  } catch {
    return false;
  }
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
