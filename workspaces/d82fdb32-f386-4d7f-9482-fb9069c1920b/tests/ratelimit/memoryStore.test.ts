import { MemoryRateLimitStore } from '../../src/ratelimit/memoryStore';

describe('MemoryRateLimitStore', () => {
  let nowSpy: jest.SpyInstance<number, []>;
  let clock = 0;

  beforeEach(() => {
    clock = 1_000_000_000_000; // aligned to a 1000ms bucket boundary
    nowSpy = jest.spyOn(Date, 'now').mockImplementation(() => clock);
  });

  afterEach(() => {
    nowSpy.mockRestore();
  });

  it('counts requests inside the same window', async () => {
    const store = new MemoryRateLimitStore();

    const first = await store.increment('k', 1000);
    expect(first).toEqual({ current: 1, previous: 0, resetAt: clock + 1000 });

    clock += 100;
    const second = await store.increment('k', 1000);
    expect(second.current).toBe(2);
    expect(second.previous).toBe(0);
    expect(second.resetAt).toBe(1_000_000_001_000);
  });

  it('rolls over to a new bucket and reports the previous count', async () => {
    const store = new MemoryRateLimitStore();

    await store.increment('k', 1000);
    await store.increment('k', 1000);

    clock += 1000; // next bucket
    const rolled = await store.increment('k', 1000);
    expect(rolled.current).toBe(1);
    expect(rolled.previous).toBe(2);
    expect(rolled.resetAt).toBe(1_000_000_002_000);

    clock += 1000; // the original bucket is now two windows old
    const later = await store.increment('k', 1000);
    expect(later.current).toBe(1);
    expect(later.previous).toBe(1);

    clock += 5000; // long idle period
    const cold = await store.increment('k', 1000);
    expect(cold.current).toBe(1);
    expect(cold.previous).toBe(0);
  });

  it('keeps keys isolated from one another', async () => {
    const store = new MemoryRateLimitStore();

    await store.increment('a', 1000);
    await store.increment('a', 1000);
    const b = await store.increment('b', 1000);

    expect(b.current).toBe(1);
  });

  it('expires stale entries lazily so the map does not grow forever', async () => {
    const store = new MemoryRateLimitStore({ sweepIntervalMs: 1000 });

    for (let i = 0; i < 50; i += 1) {
      await store.increment(`client-${i}`, 1000);
      clock += 10;
    }
    expect(store.size()).toBe(50);

    // Move well past every entry's expiry and touch the store once: the sweep
    // plus lazy read-expiry must drop all of the old buckets.
    clock += 10_000;
    await store.increment('client-fresh', 1000);
    expect(store.size()).toBe(1);
  });

  it('reset() drops every bucket for a key', async () => {
    const store = new MemoryRateLimitStore();

    await store.increment('k', 1000);
    clock += 1000;
    await store.increment('k', 1000);
    await store.reset('k');

    const afterReset = await store.increment('k', 1000);
    expect(afterReset.current).toBe(1);
    expect(afterReset.previous).toBe(0);
  });

  it('reports its kind and clears on close', async () => {
    const store = new MemoryRateLimitStore();
    expect(store.kind).toBe('memory');
    await store.increment('k', 1000);
    await store.close();
    expect(store.size()).toBe(0);
  });
});
