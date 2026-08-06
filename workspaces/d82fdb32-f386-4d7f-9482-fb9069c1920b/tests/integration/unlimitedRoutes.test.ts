import request from 'supertest';
import { buildApp } from '../../src/app';
import { metrics } from '../../src/metrics';
import { MemoryRateLimitStore } from '../../src/ratelimit/memoryStore';

describe('routes outside the limiter', () => {
  const store = new MemoryRateLimitStore();
  const { app } = buildApp({
    store,
    rateLimitConfig: { windowMs: 1000, max: 1, trustedKeys: [], keySalt: 's' },
  });
  let logSpy: jest.SpyInstance;
  let warnSpy: jest.SpyInstance;

  beforeAll(() => {
    logSpy = jest.spyOn(console, 'log').mockImplementation(() => undefined);
    warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
  });

  afterAll(async () => {
    await store.close();
    logSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it('serves an unlimited health check that names the active store', async () => {
    for (let i = 0; i < 5; i += 1) {
      const res = await request(app).get('/healthz');
      expect(res.status).toBe(200);
      expect(res.body).toEqual({ status: 'ok', rateLimitStore: 'memory' });
      expect(res.headers['ratelimit-limit']).toBeUndefined();
    }
  });

  it('exposes allowed vs rejected creation counters', async () => {
    metrics.reset();
    await request(app).post('/api/items').set('X-API-Key', 'metrics-key').send({ name: 'a' });
    await request(app).post('/api/items').set('X-API-Key', 'metrics-key').send({ name: 'b' });

    const res = await request(app).get('/internal/metrics');
    expect(res.status).toBe(200);
    expect(res.body.items_create_allowed_total).toBe(1);
    expect(res.body.items_create_rejected_total).toBe(1);
    expect(res.body.rate_limit_store_errors_total).toBe(0);
  });

  it('returns a JSON 404 for unknown routes without consuming quota', async () => {
    const res = await request(app).get('/nope');
    expect(res.status).toBe(404);
    expect(res.body).toEqual({ error: 'not_found', message: 'No such route.' });
    expect(res.headers['ratelimit-limit']).toBeUndefined();
  });
});
