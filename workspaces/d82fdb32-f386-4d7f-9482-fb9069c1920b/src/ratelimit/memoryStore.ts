import {
  IncrementResult,
  RateLimitStore,
  bucketIdFor,
  bucketResetAt,
} from './store';

interface Bucket {
  count: number;
  /** Epoch millis after which this entry is garbage. */
  expiresAt: number;
}

/**
 * Single-process store. Buckets are expired lazily: stale entries are dropped
 * on read and a full sweep runs at most once per `sweepIntervalMs`, so the map
 * cannot grow without bound even if keys are never seen again.
 */
export class MemoryRateLimitStore implements RateLimitStore {
  public readonly kind = 'memory' as const;

  private readonly buckets = new Map<string, Bucket>();
  private readonly sweepIntervalMs: number;
  private nextSweepAt = 0;

  constructor(options: { sweepIntervalMs?: number } = {}) {
    this.sweepIntervalMs = options.sweepIntervalMs ?? 30_000;
  }

  async increment(key: string, windowMs: number): Promise<IncrementResult> {
    const now = Date.now();
    this.maybeSweep(now);

    const bucketId = bucketIdFor(now, windowMs);
    const resetAt = bucketResetAt(now, windowMs);
    const currentKey = `${key}:${bucketId}`;
    const previousKey = `${key}:${bucketId - 1}`;

    const existing = this.readFresh(currentKey, now);
    const current: Bucket = existing
      ? { count: existing.count + 1, expiresAt: existing.expiresAt }
      : { count: 1, expiresAt: resetAt + windowMs };
    this.buckets.set(currentKey, current);

    const previous = this.readFresh(previousKey, now);

    return {
      current: current.count,
      previous: previous ? previous.count : 0,
      resetAt,
    };
  }

  async reset(key: string): Promise<void> {
    for (const storedKey of Array.from(this.buckets.keys())) {
      if (storedKey === key || storedKey.startsWith(`${key}:`)) {
        this.buckets.delete(storedKey);
      }
    }
  }

  async close(): Promise<void> {
    this.buckets.clear();
  }

  /** Number of live entries — exposed for the memory-leak assertions in tests. */
  size(): number {
    return this.buckets.size;
  }

  private readFresh(storeKey: string, now: number): Bucket | undefined {
    const bucket = this.buckets.get(storeKey);
    if (!bucket) return undefined;
    if (bucket.expiresAt <= now) {
      this.buckets.delete(storeKey);
      return undefined;
    }
    return bucket;
  }

  private maybeSweep(now: number): void {
    if (now < this.nextSweepAt) return;
    this.nextSweepAt = now + this.sweepIntervalMs;
    for (const [storeKey, bucket] of this.buckets) {
      if (bucket.expiresAt <= now) this.buckets.delete(storeKey);
    }
  }
}
