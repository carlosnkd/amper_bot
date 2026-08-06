import { IncrementResult } from './store';

export interface SlidingWindowDecision {
  allowed: boolean;
  /** Weighted estimate of the number of requests in the trailing window. */
  estimatedCount: number;
  limit: number;
  /** Requests left before the limit trips (never negative). */
  remaining: number;
  /** Epoch millis at which the current bucket rolls over. */
  resetAt: number;
  /** Seconds until the caller should retry (>= 1). */
  retryAfterSeconds: number;
}

/**
 * Sliding-window counter.
 *
 * Two fixed buckets are combined: the whole of the current bucket plus the
 * fraction of the previous bucket that still overlaps the trailing `windowMs`.
 * At 25% into the current bucket the previous one is weighted 0.75, at 90% it
 * is weighted 0.10 — which smooths out the burst-at-boundary problem of a plain
 * fixed window without per-request token bookkeeping.
 */
export function evaluateSlidingWindow(params: {
  result: IncrementResult;
  windowMs: number;
  max: number;
  now: number;
}): SlidingWindowDecision {
  const { result, windowMs, max, now } = params;
  const windowStart = result.resetAt - windowMs;
  const elapsedInWindow = clamp(now - windowStart, 0, windowMs);
  const previousWeight = (windowMs - elapsedInWindow) / windowMs;

  const estimatedCount = result.current + result.previous * previousWeight;
  const allowed = estimatedCount <= max;
  const remaining = Math.max(0, Math.floor(max - estimatedCount));
  const msUntilReset = Math.max(0, result.resetAt - now);
  const retryAfterSeconds = Math.max(1, Math.ceil(msUntilReset / 1000));

  return {
    allowed,
    estimatedCount,
    limit: max,
    remaining: allowed ? remaining : 0,
    resetAt: result.resetAt,
    retryAfterSeconds,
  };
}

function clamp(value: number, min: number, max: number): number {
  if (value < min) return min;
  if (value > max) return max;
  return value;
}
