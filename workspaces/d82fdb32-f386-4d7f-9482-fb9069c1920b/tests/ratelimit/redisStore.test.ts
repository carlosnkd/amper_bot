import {
  RedisLike,
  RedisRateLimitStore,
  SLIDING_WINDOW_LUA,
} from '../../src/ratelimit/redisStore';

/**
 * Minimal in-process stand-in for Redis that executes the same semantics as the
 * Lua script, so the store's key layout, TTL argument and reply parsing can be
 * asserted without a live server.
 */
class FakeRedis implements RedisLike {
  readonly values = new Map<string, number>();
  readonly ttls = new Map<string, number>();
  readonly scripts = new Map<string, string>();
  evalshaCalls = 0;
  evalCalls = 0;
  loadCalls = 0;
  failNextWithNoScript = false;

  async script(_subcommand: 'LOAD', script: string): Promise<string> {
    this.loadCalls += 1;
    const sha = `sha-${this.scripts.size + 1}`;
    this.scripts.set(sha, script);
    return sha;
  }

  async evalsha(
    sha: string,
    numKeys: number,
    ...args: (string | number)[]
  ): Promise<unknown> {
    this.evalshaCalls += 1;
    if (this.failNextWithNoScript) {
      this.failNextWithNoScript = false;
      throw new Error('NOSCRIPT No matching script.');
    }
    if (!this.scripts.has(sha)) throw new Error('NOSCRIPT No matching script.');
    return this.run(numKeys, args);
  }

  async eval(
    script: string,
    numKeys: number,
    ...args: (string | number)[]
  ): Promise<unknown> {
    this.evalCalls += 1;
    expect(script).toBe(SLIDING_WINDOW_LUA);
    return this.run(numKeys, args);
  }

  async keys(pattern: string): Promise<string[]> {
    const regex = new RegExp(
      `^${pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\\\*/g, '.*')}$`,
    );
    return Array.from(this.values.keys()).filter((key) => regex.test(key));
  }

  async del(...keys: string[]): Promise<number> {
    let removed = 0;
    for (const key of keys) {
      if (this.values.delete(key)) removed += 1;
      this.ttls.delete(key);
    }
    return removed;
  }

  async quit(): Promise<'OK'> {
    return 'OK';
  }

  private run(numKeys: number, args: (string | number)[]): [number, string] {
    const keys = args.slice(0, numKeys).map(String);
    const argv = args.slice(numKeys).map(String);
    const currentKey = keys[0] as string;
    const previousKey = keys[1] as string;

    const current = (this.values.get(currentKey) ?? 0) + 1;
    this.values.set(currentKey, current);
    if (current === 1) this.ttls.set(currentKey, Number(argv[0]));

    const previous = this.values.get(previousKey) ?? 0;
    return [current, String(previous)];
  }
}

describe('RedisRateLimitStore', () => {
  let clock = 1_700_000_000_000;
  let nowSpy: jest.SpyInstance<number, []>;

  beforeEach(() => {
    clock = 1_700_000_000_000;
    nowSpy = jest.spyOn(Date, 'now').mockImplementation(() => clock);
  });

  afterEach(() => nowSpy.mockRestore());

  it('increments the current bucket atomically in one round trip', async () => {
    const redis = new FakeRedis();
    const store = new RedisRateLimitStore(redis, { prefix: 'rl' });

    const first = await store.increment('POST:/api/items|ip:1.2.3.4', 60_000);
    expect(first.current).toBe(1);
    expect(first.previous).toBe(0);
    expect(first.resetAt).toBe(Math.floor(clock / 60_000) * 60_000 + 60_000);
    // One evalsha per increment; the script is only LOADed once.
    expect(redis.evalshaCalls).toBe(1);

    const second = await store.increment('POST:/api/items|ip:1.2.3.4', 60_000);
    expect(second.current).toBe(2);
    expect(redis.loadCalls).toBe(1);
    expect(redis.evalshaCalls).toBe(2);
  });

  it('sets the bucket TTL to two windows, only on creation', async () => {
    const redis = new FakeRedis();
    const store = new RedisRateLimitStore(redis);

    await store.increment('k', 30_000);
    const bucketId = Math.floor(clock / 30_000);
    const key = `rl:k:${bucketId}`;
    expect(redis.ttls.get(key)).toBe(60_000);

    clock += 10;
    await store.increment('k', 30_000);
    // TTL must not be pushed forward by later hits in the same bucket.
    expect(redis.ttls.get(key)).toBe(60_000);
  });

  it('reads the previous bucket after rollover', async () => {
    const redis = new FakeRedis();
    const store = new RedisRateLimitStore(redis);

    await store.increment('k', 1000);
    await store.increment('k', 1000);
    await store.increment('k', 1000);

    clock += 1000;
    const rolled = await store.increment('k', 1000);
    expect(rolled.current).toBe(1);
    expect(rolled.previous).toBe(3);
  });

  it('reloads the script inline when Redis reports NOSCRIPT', async () => {
    const redis = new FakeRedis();
    const store = new RedisRateLimitStore(redis);

    await store.increment('k', 1000);
    redis.failNextWithNoScript = true;

    const result = await store.increment('k', 1000);
    expect(result.current).toBe(2);
    expect(redis.evalCalls).toBe(1);
  });

  it('propagates non-NOSCRIPT errors so the middleware can fail open', async () => {
    const redis = new FakeRedis();
    redis.evalsha = async () => {
      throw new Error('CONNECTION_BROKEN');
    };
    const store = new RedisRateLimitStore(redis);

    await expect(store.increment('k', 1000)).rejects.toThrow('CONNECTION_BROKEN');
  });

  it('reset() deletes every bucket for the key', async () => {
    const redis = new FakeRedis();
    const store = new RedisRateLimitStore(redis);

    await store.increment('k', 1000);
    clock += 1000;
    await store.increment('k', 1000);
    await store.increment('other', 1000);

    await store.reset('k');

    expect(await redis.keys('rl:k:*')).toEqual([]);
    expect((await redis.keys('rl:other:*')).length).toBe(1);
  });

  it('exposes its kind', () => {
    expect(new RedisRateLimitStore(new FakeRedis()).kind).toBe('redis');
  });
});
