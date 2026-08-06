import type { Request, Response } from 'express';
import { MemoryRateLimitStore } from '../../src/ratelimit/memoryStore';
import { rateLimit } from '../../src/ratelimit/middleware';
import { IncrementResult, RateLimitStore } from '../../src/ratelimit/store';

interface FakeRes {
  statusCode: number | undefined;
  headers: Record<string, string>;
  body: unknown;
  setHeader: jest.Mock;
  status: jest.Mock;
  json: jest.Mock;
}

function makeRes(): FakeRes {
  const res: FakeRes = {
    statusCode: undefined,
    headers: {},
    body: undefined,
    setHeader: jest.fn(),
    status: jest.fn(),
    json: jest.fn(),
  };
  res.setHeader.mockImplementation((name: string, value: string) => {
    res.headers[name] = value;
    return res;
  });
  res.status.mockImplementation((code: number) => {
    res.statusCode = code;
    return res;
  });
  res.json.mockImplementation((payload: unknown) => {
    res.body = payload;
    return res;
  });
  return res;
}

function makeReq(overrides: Partial<Request> = {}): Request {
  return {
    method: 'POST',
    originalUrl: '/api/items',
    headers: {},
    ...overrides,
  } as unknown as Request;
}

function run(
  handler: ReturnType<typeof rateLimit>,
  req: Request,
  res: FakeRes,
): Promise<{ nextCalled: boolean }> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (nextCalled: boolean) => {
      if (settled) return;
      settled = true;
      resolve({ nextCalled });
    };
    res.json.mockImplementation((payload: unknown) => {
      res.body = payload;
      finish(false);
      return res;
    });
    handler(req, res as unknown as Response, (() => finish(true)) as never);
  });
}

describe('rateLimit middleware', () => {
  it('allows requests under the limit and sets RateLimit headers', async () => {
    const store = new MemoryRateLimitStore();
    const handler = rateLimit({
      store,
      windowMs: 60_000,
      max: 3,
      route: 'POST:/api/items',
      keyGenerator: () => 'client-a',
    });

    const remainings: string[] = [];
    for (let i = 0; i < 3; i += 1) {
      const res = makeRes();
      const { nextCalled } = await run(handler, makeReq(), res);
      expect(nextCalled).toBe(true);
      expect(res.headers['RateLimit-Limit']).toBe('3');
      remainings.push(res.headers['RateLimit-Remaining'] as string);
      expect(Number(res.headers['RateLimit-Reset'])).toBeGreaterThan(0);
    }
    expect(remainings).toEqual(['2', '1', '0']);
  });

  it('rejects with 429, Retry-After and the JSON error contract', async () => {
    const store = new MemoryRateLimitStore();
    const handler = rateLimit({
      store,
      windowMs: 60_000,
      max: 1,
      keyGenerator: () => 'client-b',
    });

    await run(handler, makeReq(), makeRes());
    const res = makeRes();
    const { nextCalled } = await run(handler, makeReq(), res);

    expect(nextCalled).toBe(false);
    expect(res.statusCode).toBe(429);
    expect(Number(res.headers['Retry-After'])).toBeGreaterThanOrEqual(1);
    expect(res.headers['RateLimit-Remaining']).toBe('0');
    expect(res.body).toMatchObject({
      error: 'rate_limit_exceeded',
      retryAfterSeconds: expect.any(Number),
    });
    expect(String((res.body as { message: string }).message)).toContain('Limit is 1');
  });

  it('honours the skip predicate without touching the store', async () => {
    const store = new MemoryRateLimitStore();
    const incrementSpy = jest.spyOn(store, 'increment');
    const handler = rateLimit({
      store,
      windowMs: 60_000,
      max: 0,
      keyGenerator: () => 'client-c',
      skip: () => true,
    });

    const res = makeRes();
    const { nextCalled } = await run(handler, makeReq(), res);
    expect(nextCalled).toBe(true);
    expect(incrementSpy).not.toHaveBeenCalled();
    expect(res.headers['RateLimit-Limit']).toBeUndefined();
  });

  it('keeps separate budgets per generated key', async () => {
    const store = new MemoryRateLimitStore();
    let key = 'a';
    const handler = rateLimit({
      store,
      windowMs: 60_000,
      max: 1,
      keyGenerator: () => key,
    });

    await run(handler, makeReq(), makeRes());
    const blocked = await run(handler, makeReq(), makeRes());
    expect(blocked.nextCalled).toBe(false);

    key = 'b';
    const allowed = await run(handler, makeReq(), makeRes());
    expect(allowed.nextCalled).toBe(true);
  });

  it('fails open when the store throws, reporting the error', async () => {
    const brokenStore: RateLimitStore = {
      kind: 'redis',
      increment: async (): Promise<IncrementResult> => {
        throw new Error('redis down');
      },
      reset: async () => undefined,
      close: async () => undefined,
    };
    const onStoreError = jest.fn();
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);

    const handler = rateLimit({
      store: brokenStore,
      windowMs: 60_000,
      max: 1,
      keyGenerator: () => 'client-d',
      onStoreError,
    });

    const res = makeRes();
    const { nextCalled } = await run(handler, makeReq(), res);

    expect(nextCalled).toBe(true);
    expect(res.statusCode).toBeUndefined();
    expect(onStoreError).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it('logs a structured rejection line with hashed key, route and limit', async () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
    const store = new MemoryRateLimitStore();
    const handler = rateLimit({
      store,
      windowMs: 60_000,
      max: 1,
      route: 'POST:/api/items',
      keyGenerator: () => 'POST:/api/items|key:deadbeef',
    });

    await run(handler, makeReq(), makeRes());
    await run(handler, makeReq(), makeRes());

    const lines = warn.mock.calls.map((call) => JSON.parse(String(call[0])));
    const rejection = lines.find((line) => line.msg === 'rate_limit_rejected');
    expect(rejection).toMatchObject({
      level: 'warn',
      route: 'POST:/api/items',
      key: 'POST:/api/items|key:deadbeef',
      limit: 1,
      method: 'POST',
      path: '/api/items',
    });
    warn.mockRestore();
  });

  it('exposes the decision on req.rateLimit', async () => {
    const store = new MemoryRateLimitStore();
    const handler = rateLimit({
      store,
      windowMs: 60_000,
      max: 5,
      keyGenerator: () => 'client-e',
    });

    const req = makeReq();
    await run(handler, req, makeRes());
    expect(req.rateLimit).toMatchObject({ key: 'client-e', limit: 5, remaining: 4 });
  });
});
