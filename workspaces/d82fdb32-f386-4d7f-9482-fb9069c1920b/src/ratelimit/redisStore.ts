import {
  IncrementResult,
  RateLimitStore,
  bucketIdFor,
  bucketResetAt,
} from './store';

/**
 * The slice of the ioredis surface this store actually needs. Declaring it
 * locally keeps the store unit-testable with a fake client and avoids a hard
 * compile-time dependency on ioredis' types.
 */
export interface RedisLike {
  evalsha(sha: string, numKeys: number, ...args: (string | number)[]): Promise<unknown>;
  eval(script: string, numKeys: number, ...args: (string | number)[]): Promise<unknown>;
  script(subcommand: 'LOAD', script: string): Promise<unknown>;
  keys(pattern: string): Promise<string[]>;
  del(...keys: string[]): Promise<unknown>;
  quit(): Promise<unknown>;
}

/**
 * One round trip, atomic:
 *   KEYS[1] current bucket, KEYS[2] previous bucket, ARGV[1] bucket TTL in ms.
 * INCR the current bucket, set its TTL only on creation (so the TTL is not
 * pushed forward by later hits in the same bucket), then read the previous
 * bucket. Because this runs inside Redis, concurrent requests from multiple app
 * instances cannot both read a pre-increment count and slip past the limit.
 */
export const SLIDING_WINDOW_LUA = `
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
local previous = redis.call('GET', KEYS[2])
if previous == false then
  previous = '0'
end
return { current, previous }
`;

export class RedisRateLimitStore implements RateLimitStore {
  public readonly kind = 'redis' as const;

  private readonly client: RedisLike;
  private readonly prefix: string;
  private scriptSha: string | null = null;

  constructor(client: RedisLike, options: { prefix?: string } = {}) {
    this.client = client;
    this.prefix = options.prefix ?? 'rl';
  }

  async increment(key: string, windowMs: number): Promise<IncrementResult> {
    const now = Date.now();
    const bucketId = bucketIdFor(now, windowMs);
    const resetAt = bucketResetAt(now, windowMs);
    // Keep a bucket alive for two windows so it can still be read as the
    // "previous" bucket after rollover.
    const ttlMs = windowMs * 2;

    const currentKey = this.storeKey(key, bucketId);
    const previousKey = this.storeKey(key, bucketId - 1);

    const raw = await this.runScript([currentKey, previousKey], [ttlMs]);
    const [current, previous] = this.parse(raw);

    return { current, previous, resetAt };
  }

  async reset(key: string): Promise<void> {
    const keys = await this.client.keys(`${this.prefix}:${key}:*`);
    if (keys.length > 0) {
      await this.client.del(...keys);
    }
  }

  async close(): Promise<void> {
    try {
      await this.client.quit();
    } catch {
      // Connection already gone — nothing to release.
    }
  }

  private storeKey(key: string, bucketId: number): string {
    return `${this.prefix}:${key}:${bucketId}`;
  }

  private async runScript(
    keys: string[],
    args: (string | number)[],
  ): Promise<unknown> {
    if (!this.scriptSha) {
      const loaded = await this.client.script('LOAD', SLIDING_WINDOW_LUA);
      this.scriptSha = String(loaded);
    }
    try {
      return await this.client.evalsha(
        this.scriptSha,
        keys.length,
        ...keys,
        ...args,
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (!message.includes('NOSCRIPT')) throw err;
      // Script cache was flushed; reload inline and let the next call re-cache.
      this.scriptSha = null;
      return this.client.eval(
        SLIDING_WINDOW_LUA,
        keys.length,
        ...keys,
        ...args,
      );
    }
  }

  private parse(raw: unknown): [number, number] {
    if (!Array.isArray(raw) || raw.length < 2) {
      throw new Error('Unexpected reply from rate limit script');
    }
    return [toInt(raw[0]), toInt(raw[1])];
  }
}

function toInt(value: unknown): number {
  if (typeof value === 'number') return value;
  if (typeof value === 'string') {
    const parsed = Number.parseInt(value, 10);
    return Number.isNaN(parsed) ? 0 : parsed;
  }
  if (value instanceof Buffer) return toInt(value.toString('utf8'));
  return 0;
}
