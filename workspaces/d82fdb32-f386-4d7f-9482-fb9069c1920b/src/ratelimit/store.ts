/**
 * Storage contract for the sliding-window counter.
 *
 * The window is split into fixed buckets of `windowMs`. A single `increment`
 * call bumps the counter for the bucket that `now` falls into and reports the
 * counter of the *previous* bucket, which the algorithm weights to approximate
 * a true sliding window.
 */
export interface IncrementResult {
  /** Count in the current bucket, including this request. */
  current: number;
  /** Count in the immediately preceding bucket (0 if it has expired). */
  previous: number;
  /** Epoch millis at which the current bucket rolls over. */
  resetAt: number;
}

export interface RateLimitStore {
  /**
   * Atomically increments the current bucket for `key` and returns the
   * counters needed to evaluate the sliding window.
   */
  increment(key: string, windowMs: number): Promise<IncrementResult>;

  /** Drops all buckets for `key`. Primarily used by tests. */
  reset(key: string): Promise<void>;

  /** Releases any underlying resources (connections, timers). */
  close(): Promise<void>;

  /** Human readable store name, used in logs. */
  readonly kind: 'memory' | 'redis';
}

/** Bucket index for a point in time. */
export function bucketIdFor(now: number, windowMs: number): number {
  return Math.floor(now / windowMs);
}

/** Epoch millis at which the bucket containing `now` rolls over. */
export function bucketResetAt(now: number, windowMs: number): number {
  return (bucketIdFor(now, windowMs) + 1) * windowMs;
}
