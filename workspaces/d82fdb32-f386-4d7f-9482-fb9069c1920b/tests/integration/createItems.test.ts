import { randomUUID } from 'crypto';
import request from 'supertest';
import { buildApp, type BuiltApp } from '../../src/app';
import { metrics } from '../../src/metrics';
import { RateLimitStore } from '../../src/ratelimit/store';
import { isStoreReachable, sleep, storeCandidates } from '../helpers/stores';

const WINDOW_MS = 2000;
const MAX = 3;

/**
 * Requests must all land in the same fixed bucket for the header assertions to
 * be deterministic, so wait out the tail end of a bucket when it is nearly over.
 */
async function alignToFreshBucket(windowMs: number, minMs: number): Promise<void> {
  const now = Date.now();
  const msLeft = (Math.floor(now / windowMs) + 1) * windowMs - now;
  if (msLeft < minMs) await sleep(msLeft + 10);
}

for (const candidate of storeCandidates()) {
  describe(`POST /api/items rate limiting (${candidate.name} store)`, () => {
    let store: RateLimitStore;
    let available = true;
    let logSpy: jest.SpyInstance;
    let warnSpy: jest.SpyInstance;

    beforeAll(async () => {
      logSpy = jest.spyOn(console, 'log').mockImplementation(() => undefined);
      warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
      store = candidate.create();
      available = await isStoreReachable(store);
      if (!available) {
        // eslint-disable-next-line no-console
        process.stderr.write(
          `[skip] ${candidate.name} store unreachable — skipping its integration tests\n`,
        );
      }
    });

    afterAll(async () => {
      if (store) await store.close();
      logSpy.mockRestore();
      warnSpy.mockRestore();
    });

    beforeEach(() => {
      metrics.reset();
    });

    /** it() that no-ops when this store is not reachable in this environment. */
    const itStore = (name: string, fn: () => Promise<void>): void => {
      it(name, async () => {
        if (!available) return;
        await fn();
      });
    };

    /** A fresh app whose store keys are namespaced per test, so runs never collide. */
    function makeApp(overrides: { max?: number; trustedKeys?: string[] } = {}): BuiltApp {
      return buildApp({
        store,
        rateLimitRoute: `test:${randomUUID()}`,
        rateLimitConfig: {
          windowMs: WINDOW_MS,
          max: overrides.max ?? MAX,
          trustedKeys: overrides.trustedKeys ?? [],
          keySalt: 'integration-salt',
        },
      });
    }

    itStore('allows creates under the limit with a decreasing Remaining header', async () => {
      const { app } = makeApp();
      const apiKey = `key-${randomUUID()}`;
      await alignToFreshBucket(WINDOW_MS, 1500);

      const remainings: string[] = [];
      for (let i = 0; i < MAX; i += 1) {
        const res = await request(app)
          .post('/api/items')
          .set('X-API-Key', apiKey)
          .send({ name: `item-${i}` });

        expect(res.status).toBe(201);
        expect(res.body.item).toMatchObject({ name: `item-${i}` });
        expect(res.headers['ratelimit-limit']).toBe(String(MAX));
        expect(Number(res.headers['ratelimit-reset'])).toBeGreaterThanOrEqual(0);
        remainings.push(res.headers['ratelimit-remaining'] as string);
      }

      expect(remainings).toEqual(['2', '1', '0']);
      expect(metrics.get('items_create_allowed_total')).toBe(MAX);
      expect(metrics.get('items_create_rejected_total')).toBe(0);
    });

    itStore('rejects the request past the limit with 429, Retry-After and the JSON body', async () => {
      const { app } = makeApp();
      const apiKey = `key-${randomUUID()}`;
      await alignToFreshBucket(WINDOW_MS, 1500);

      for (let i = 0; i < MAX; i += 1) {
        await request(app)
          .post('/api/items')
          .set('X-API-Key', apiKey)
          .send({ name: `item-${i}` })
          .expect(201);
      }

      const res = await request(app)
        .post('/api/items')
        .set('X-API-Key', apiKey)
        .send({ name: 'one-too-many' });

      expect(res.status).toBe(429);
      expect(Number(res.headers['retry-after'])).toBeGreaterThanOrEqual(1);
      expect(res.headers['ratelimit-limit']).toBe(String(MAX));
      expect(res.headers['ratelimit-remaining']).toBe('0');
      expect(res.body).toEqual({
        error: 'rate_limit_exceeded',
        message: expect.stringContaining('Too many requests'),
        retryAfterSeconds: expect.any(Number),
      });
      expect(metrics.get('items_create_rejected_total')).toBe(1);
    });

    itStore('never leaks the raw API key into the rejection log line', async () => {
      const { app } = makeApp({ max: 1 });
      const apiKey = `super-secret-${randomUUID()}`;
      await alignToFreshBucket(WINDOW_MS, 1500);

      warnSpy.mockClear();
      await request(app).post('/api/items').set('X-API-Key', apiKey).send({ name: 'a' });
      await request(app)
        .post('/api/items')
        .set('X-API-Key', apiKey)
        .send({ name: 'b' })
        .expect(429);

      const lines = warnSpy.mock.calls.map((call) => String(call[0]));
      const rejection = lines.find((line) => line.includes('rate_limit_rejected'));
      expect(rejection).toBeDefined();
      expect(rejection).not.toContain(apiKey);
      const parsed = JSON.parse(String(rejection));
      expect(parsed).toMatchObject({ limit: 1, method: 'POST', path: '/api/items' });
      expect(String(parsed.route)).toContain('test:');
    });

    itStore('lets the client through again once the window has expired', async () => {
      const { app } = makeApp({ max: 1 });
      const apiKey = `key-${randomUUID()}`;
      await alignToFreshBucket(WINDOW_MS, 1500);

      await request(app)
        .post('/api/items')
        .set('X-API-Key', apiKey)
        .send({ name: 'first' })
        .expect(201);
      await request(app)
        .post('/api/items')
        .set('X-API-Key', apiKey)
        .send({ name: 'blocked' })
        .expect(429);

      // Wait for the exhausted bucket to fall completely out of the trailing
      // window (two bucket lengths), then the budget is whole again.
      await sleep(WINDOW_MS * 2 + 100);

      const res = await request(app)
        .post('/api/items')
        .set('X-API-Key', apiKey)
        .send({ name: 'after-reset' });

      expect(res.status).toBe(201);
      expect(res.headers['ratelimit-remaining']).toBe('0');
    });

    itStore('gives two different API keys independent budgets', async () => {
      const { app } = makeApp({ max: 2 });
      const keyA = `key-a-${randomUUID()}`;
      const keyB = `key-b-${randomUUID()}`;
      await alignToFreshBucket(WINDOW_MS, 1500);

      await request(app).post('/api/items').set('X-API-Key', keyA).send({ name: '1' }).expect(201);
      await request(app).post('/api/items').set('X-API-Key', keyA).send({ name: '2' }).expect(201);
      await request(app).post('/api/items').set('X-API-Key', keyA).send({ name: '3' }).expect(429);

      const res = await request(app)
        .post('/api/items')
        .set('X-API-Key', keyB)
        .send({ name: 'other-tenant' });
      expect(res.status).toBe(201);
      expect(res.headers['ratelimit-remaining']).toBe('1');
    });

    itStore('never limits GET /api/items, even after creates are exhausted', async () => {
      const { app } = makeApp({ max: 1 });
      const apiKey = `key-${randomUUID()}`;
      await alignToFreshBucket(WINDOW_MS, 1500);

      await request(app).post('/api/items').set('X-API-Key', apiKey).send({ name: 'x' }).expect(201);
      await request(app).post('/api/items').set('X-API-Key', apiKey).send({ name: 'y' }).expect(429);

      for (let i = 0; i < 8; i += 1) {
        const res = await request(app).get('/api/items').set('X-API-Key', apiKey);
        expect(res.status).toBe(200);
        expect(res.body.count).toBe(1);
        // The limiter is not mounted here at all, so no headers are emitted.
        expect(res.headers['ratelimit-limit']).toBeUndefined();
        expect(res.headers['ratelimit-remaining']).toBeUndefined();
      }
    });

    itStore('lets trusted keys bypass the limit entirely', async () => {
      const trusted = `partner-${randomUUID()}`;
      const { app } = makeApp({ max: 1, trustedKeys: [trusted] });
      await alignToFreshBucket(WINDOW_MS, 1500);

      for (let i = 0; i < 6; i += 1) {
        const res = await request(app)
          .post('/api/items')
          .set('X-API-Key', trusted)
          .send({ name: `bulk-${i}` });
        expect(res.status).toBe(201);
        expect(res.headers['ratelimit-limit']).toBeUndefined();
      }

      // A non-trusted key on the same app is still limited.
      await request(app)
        .post('/api/items')
        .set('X-API-Key', 'ordinary')
        .send({ name: 'a' })
        .expect(201);
      await request(app)
        .post('/api/items')
        .set('X-API-Key', 'ordinary')
        .send({ name: 'b' })
        .expect(429);
    });

    itStore('falls back to the client IP when no API key is sent', async () => {
      const { app } = makeApp({ max: 1 });
      await alignToFreshBucket(WINDOW_MS, 1500);

      await request(app).post('/api/items').send({ name: 'ip-1' }).expect(201);
      const blocked = await request(app).post('/api/items').send({ name: 'ip-2' });
      expect(blocked.status).toBe(429);

      // An API key on the same connection gets its own, untouched budget.
      await request(app)
        .post('/api/items')
        .set('X-API-Key', `key-${randomUUID()}`)
        .send({ name: 'keyed' })
        .expect(201);
    });

    itStore('charges quota before body validation runs', async () => {
      const { app } = makeApp({ max: 1 });
      const apiKey = `key-${randomUUID()}`;
      await alignToFreshBucket(WINDOW_MS, 1500);

      const invalid = await request(app)
        .post('/api/items')
        .set('X-API-Key', apiKey)
        .send({ name: '' });
      expect(invalid.status).toBe(400);
      expect(invalid.body.error).toBe('validation_failed');
      // Header proves the limiter already ran and consumed the request.
      expect(invalid.headers['ratelimit-remaining']).toBe('0');

      const next = await request(app)
        .post('/api/items')
        .set('X-API-Key', apiKey)
        .send({ name: 'valid' });
      expect(next.status).toBe(429);
    });

    itStore('shares one budget across app instances backed by the same store', async () => {
      const route = `test:${randomUUID()}`;
      const config = {
        windowMs: WINDOW_MS,
        max: 2,
        trustedKeys: [] as string[],
        keySalt: 'integration-salt',
      };
      const instanceA = buildApp({ store, rateLimitRoute: route, rateLimitConfig: config });
      const instanceB = buildApp({ store, rateLimitRoute: route, rateLimitConfig: config });
      const apiKey = `key-${randomUUID()}`;
      await alignToFreshBucket(WINDOW_MS, 1500);

      await request(instanceA.app)
        .post('/api/items')
        .set('X-API-Key', apiKey)
        .send({ name: '1' })
        .expect(201);
      await request(instanceB.app)
        .post('/api/items')
        .set('X-API-Key', apiKey)
        .send({ name: '2' })
        .expect(201);
      await request(instanceB.app)
        .post('/api/items')
        .set('X-API-Key', apiKey)
        .send({ name: '3' })
        .expect(429);
    });
  });
}
