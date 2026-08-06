import type { Request, RequestHandler } from 'express';
import { logger } from '../logger';
import { metrics } from '../metrics';
import {
  CREATE_ITEMS_ROUTE,
  loadCreateItemsLimitConfig,
  RateLimitConfig,
} from './config';
import { makeKeyGenerator, readApiKey } from './identity';
import { rateLimit } from './middleware';
import { RateLimitStore } from './store';

export interface CreateItemsLimiterOptions {
  store: RateLimitStore;
  /** Defaults to the env-driven config. */
  config?: Partial<RateLimitConfig>;
  /** Route namespace for store keys. Defaults to `POST:/api/items`. */
  route?: string;
}

/**
 * The limiter for the single guarded endpoint. Bundles: the route-namespaced
 * key generator (hashed API key, else trust-proxy-aware IP), the trusted-key
 * bypass, and the allowed/rejected metrics.
 */
export function createItemsRateLimiter(
  options: CreateItemsLimiterOptions,
): RequestHandler {
  const base = loadCreateItemsLimitConfig();
  const config: RateLimitConfig = { ...base, ...options.config };
  const route = options.route ?? CREATE_ITEMS_ROUTE;
  const trusted = new Set(config.trustedKeys);

  logger.info('rate_limit_configured', {
    route,
    windowMs: config.windowMs,
    max: config.max,
    store: options.store.kind,
    trustedKeyCount: trusted.size,
  });

  return rateLimit({
    store: options.store,
    windowMs: config.windowMs,
    max: config.max,
    route,
    keyGenerator: makeKeyGenerator({ route, salt: config.keySalt }),
    skip: (req: Request) => {
      if (trusted.size === 0) return false;
      const apiKey = readApiKey(req);
      return apiKey !== undefined && trusted.has(apiKey);
    },
    onAllowed: () => metrics.increment('items_create_allowed_total'),
    onRejected: () => metrics.increment('items_create_rejected_total'),
    onStoreError: () => metrics.increment('rate_limit_store_errors_total'),
  });
}
