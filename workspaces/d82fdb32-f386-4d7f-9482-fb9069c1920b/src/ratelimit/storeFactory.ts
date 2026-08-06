import { logger } from '../logger';
import { MemoryRateLimitStore } from './memoryStore';
import { RedisLike, RedisRateLimitStore } from './redisStore';
import { RateLimitStore } from './store';

export interface StoreFactoryOptions {
  /** Defaults to process.env.REDIS_URL. */
  redisUrl?: string | undefined;
  /** Key prefix for the Redis store. */
  prefix?: string;
}

/**
 * Returns the Redis store when a REDIS_URL is configured (so the limit holds
 * across app instances) and the in-memory store otherwise (local dev, tests).
 * If ioredis cannot be loaded or the URL is unusable we fall back to memory
 * rather than failing startup.
 */
export function createRateLimitStore(
  options: StoreFactoryOptions = {},
): RateLimitStore {
  const redisUrl =
    options.redisUrl !== undefined ? options.redisUrl : process.env.REDIS_URL;

  if (!redisUrl) {
    logger.info('rate_limit_store_selected', { store: 'memory' });
    return new MemoryRateLimitStore();
  }

  try {
    const client = createRedisClient(redisUrl);
    logger.info('rate_limit_store_selected', { store: 'redis' });
    return new RedisRateLimitStore(client, { prefix: options.prefix ?? 'rl' });
  } catch (err) {
    logger.warn('rate_limit_store_redis_unavailable_falling_back_to_memory', {
      error: err instanceof Error ? err.message : String(err),
    });
    return new MemoryRateLimitStore();
  }
}

function createRedisClient(redisUrl: string): RedisLike {
  // Required lazily so the app (and the test suite) runs without ioredis
  // present when Redis is not in use.
  /* eslint-disable @typescript-eslint/no-var-requires */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const IORedis = require('ioredis') as any;
  const Ctor = IORedis.default ?? IORedis;
  const client = new Ctor(redisUrl, {
    // Fail fast: the limiter fails open, so a hanging command is worse than an
    // error we can catch.
    maxRetriesPerRequest: 1,
    enableOfflineQueue: false,
    connectTimeout: 1000,
    lazyConnect: false,
  });
  client.on('error', (err: Error) => {
    logger.warn('rate_limit_redis_error', { error: err.message });
  });
  return client as RedisLike;
}
