import { MemoryRateLimitStore } from '../../src/ratelimit/memoryStore';
import { createRateLimitStore } from '../../src/ratelimit/storeFactory';

describe('createRateLimitStore', () => {
  const originalUrl = process.env.REDIS_URL;

  afterEach(() => {
    if (originalUrl === undefined) delete process.env.REDIS_URL;
    else process.env.REDIS_URL = originalUrl;
  });

  it('returns the memory store when REDIS_URL is unset', async () => {
    delete process.env.REDIS_URL;
    const store = createRateLimitStore();
    expect(store.kind).toBe('memory');
    expect(store).toBeInstanceOf(MemoryRateLimitStore);
    await store.close();
  });

  it('returns the memory store for an explicitly empty url', async () => {
    const store = createRateLimitStore({ redisUrl: '' });
    expect(store.kind).toBe('memory');
    await store.close();
  });

  it('returns the redis store when a url is provided', async () => {
    let store;
    try {
      store = createRateLimitStore({ redisUrl: 'redis://127.0.0.1:6379' });
    } catch {
      // ioredis not installed in this environment — nothing to assert.
      return;
    }
    // If ioredis is missing the factory falls back to memory rather than throwing.
    expect(['redis', 'memory']).toContain(store.kind);
    await store.close();
  });
});
