import express, { type Application, type RequestHandler } from 'express';
import { ItemsRepository } from './items/itemsRepository';
import { createItemsRouter } from './items/itemsRouter';
import { metrics } from './metrics';
import { trustProxyHops, type RateLimitConfig } from './ratelimit/config';
import { createItemsRateLimiter } from './ratelimit/createItemsLimiter';
import { createRateLimitStore } from './ratelimit/storeFactory';
import { RateLimitStore } from './ratelimit/store';

export interface BuildAppOptions {
  /** Defaults to the factory's choice (Redis when REDIS_URL is set). */
  store?: RateLimitStore;
  /** Overrides for the creation-endpoint limit; env values fill the gaps. */
  rateLimitConfig?: Partial<RateLimitConfig>;
  /**
   * Store-key namespace for the limiter. Defaults to `POST:/api/items`.
   * Tests override it to keep runs isolated in a shared Redis.
   */
  rateLimitRoute?: string;
  repository?: ItemsRepository;
}

export interface BuiltApp {
  app: Application;
  store: RateLimitStore;
  repository: ItemsRepository;
  /** Pre-built limiter, exported so tests can assert on it directly. */
  createLimiter: RequestHandler;
}

export function buildApp(options: BuildAppOptions = {}): BuiltApp {
  const store = options.store ?? createRateLimitStore();
  const repository = options.repository ?? new ItemsRepository();

  const app = express();
  const hops = trustProxyHops();
  if (hops > 0) {
    // Only trust as many proxy hops as are actually deployed, otherwise a
    // client could spoof X-Forwarded-For and mint itself a fresh budget.
    app.set('trust proxy', hops);
  } else {
    app.set('trust proxy', false);
  }

  app.use(express.json({ limit: '100kb' }));

  const createLimiter = createItemsRateLimiter({
    store,
    ...(options.rateLimitConfig ? { config: options.rateLimitConfig } : {}),
    ...(options.rateLimitRoute ? { route: options.rateLimitRoute } : {}),
  });

  // Unlimited liveness probe.
  app.get('/healthz', (_req, res) => {
    res.status(200).json({ status: 'ok', rateLimitStore: store.kind });
  });

  // Unlimited: allowed vs rejected creation counters.
  app.get('/internal/metrics', (_req, res) => {
    res.status(200).json(metrics.snapshot());
  });

  // The limiter is applied inside this router, on POST /api/items only.
  app.use('/api', createItemsRouter({ repository, createLimiter }));

  app.use((_req, res) => {
    res.status(404).json({ error: 'not_found', message: 'No such route.' });
  });

  return { app, store, repository, createLimiter };
}
