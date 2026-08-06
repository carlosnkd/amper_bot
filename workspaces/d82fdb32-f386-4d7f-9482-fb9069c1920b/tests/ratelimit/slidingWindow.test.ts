import { evaluateSlidingWindow } from '../../src/ratelimit/slidingWindow';

const windowMs = 60_000;
const max = 10;
const resetAt = 1_000_060_000; // window covers 1_000_000_000 .. 1_000_060_000

describe('evaluateSlidingWindow', () => {
  it('allows a request that lands exactly on the limit', () => {
    const decision = evaluateSlidingWindow({
      result: { current: 10, previous: 0, resetAt },
      windowMs,
      max,
      now: resetAt - windowMs + 1000,
    });

    expect(decision.allowed).toBe(true);
    expect(decision.remaining).toBe(0);
    expect(decision.limit).toBe(10);
  });

  it('denies the request past the limit', () => {
    const decision = evaluateSlidingWindow({
      result: { current: 11, previous: 0, resetAt },
      windowMs,
      max,
      now: resetAt - windowMs + 1000,
    });

    expect(decision.allowed).toBe(false);
    expect(decision.remaining).toBe(0);
  });

  it('decreases remaining one at a time', () => {
    const remainings = [1, 2, 3].map(
      (current) =>
        evaluateSlidingWindow({
          result: { current, previous: 0, resetAt },
          windowMs,
          max,
          now: resetAt - windowMs,
        }).remaining,
    );

    expect(remainings).toEqual([9, 8, 7]);
  });

  it('weights the previous window by the un-elapsed fraction', () => {
    // 25% into the current bucket => previous bucket counts for 75%.
    const quarterIn = evaluateSlidingWindow({
      result: { current: 1, previous: 8, resetAt },
      windowMs,
      max,
      now: resetAt - windowMs + windowMs * 0.25,
    });
    expect(quarterIn.estimatedCount).toBeCloseTo(1 + 8 * 0.75, 6);
    expect(quarterIn.allowed).toBe(true);
    expect(quarterIn.remaining).toBe(2);

    // 90% in => previous bucket counts for only 10%.
    const nearEnd = evaluateSlidingWindow({
      result: { current: 1, previous: 8, resetAt },
      windowMs,
      max,
      now: resetAt - windowMs + windowMs * 0.9,
    });
    expect(nearEnd.estimatedCount).toBeCloseTo(1 + 8 * 0.1, 6);
    expect(nearEnd.remaining).toBe(8);
  });

  it('blocks a boundary burst that a fixed window would let through', () => {
    // A client used its full budget in the previous bucket and immediately
    // fires again 1ms into the new one. A fixed window would reset and allow it.
    const decision = evaluateSlidingWindow({
      result: { current: 1, previous: 10, resetAt },
      windowMs,
      max,
      now: resetAt - windowMs + 1,
    });

    expect(decision.allowed).toBe(false);
    expect(decision.estimatedCount).toBeGreaterThan(max);
  });

  it('lets the same client through once the previous window has decayed', () => {
    const decision = evaluateSlidingWindow({
      result: { current: 1, previous: 10, resetAt },
      windowMs,
      max,
      now: resetAt - 1, // 99.99% through the current bucket
    });

    expect(decision.allowed).toBe(true);
  });

  it('reports retry-after as whole seconds until reset, at least 1', () => {
    const decision = evaluateSlidingWindow({
      result: { current: 20, previous: 0, resetAt },
      windowMs,
      max,
      now: resetAt - 4200,
    });
    expect(decision.retryAfterSeconds).toBe(5);

    const atBoundary = evaluateSlidingWindow({
      result: { current: 20, previous: 0, resetAt },
      windowMs,
      max,
      now: resetAt,
    });
    expect(atBoundary.retryAfterSeconds).toBe(1);
  });

  it('clamps the previous-window weight when the clock drifts', () => {
    const drifted = evaluateSlidingWindow({
      result: { current: 1, previous: 10, resetAt },
      windowMs,
      max,
      now: resetAt + 5_000, // past the reset
    });
    expect(drifted.estimatedCount).toBe(1);
    expect(drifted.allowed).toBe(true);
  });
});
