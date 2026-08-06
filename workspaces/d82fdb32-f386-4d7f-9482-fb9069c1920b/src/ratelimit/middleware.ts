import type { NextFunction, Request, RequestHandler, Response } from 'express';
import { logger } from '../logger';
import { evaluateSlidingWindow, SlidingWindowDecision } from './slidingWindow';
import { RateLimitStore } from './store';

export interface RateLimitOptions {
  store: RateLimitStore;
  /** Trailing window length in milliseconds. */
  windowMs: number;
  /** Max requests per client per window. */
  max: number;
  /** Builds the store key for a request (already namespaced by route). */
  keyGenerator: (req: Request) => string;
  /** Return true to bypass the limiter for this request. */
  skip?: (req: Request) => boolean;
  /** Route label used in logs. */
  route?: string;
  /** Called after a request is allowed through. */
  onAllowed?: (req: Request, decision: SlidingWindowDecision) => void;
  /** Called when a request is rejected with 429. */
  onRejected?: (req: Request, decision: SlidingWindowDecision) => void;
  /** Called when the store failed and the limiter failed open. */
  onStoreError?: (req: Request, error: unknown) => void;
}

export interface RateLimitInfo extends SlidingWindowDecision {
  key: string;
}

declare module 'express-serve-static-core' {
  interface Request {
    rateLimit?: RateLimitInfo;
  }
}

/**
 * Sliding-window rate limiter as plain Express middleware, so it can be dropped
 * onto a single route handler. Fails open: if the store errors (e.g. Redis is
 * unreachable) the request is allowed and a warning is logged.
 */
export function rateLimit(options: RateLimitOptions): RequestHandler {
  const {
    store,
    windowMs,
    max,
    keyGenerator,
    skip,
    route = 'unknown',
    onAllowed,
    onRejected,
    onStoreError,
  } = options;

  return function rateLimitMiddleware(
    req: Request,
    res: Response,
    next: NextFunction,
  ): void {
    if (skip && skip(req)) {
      next();
      return;
    }

    const key = keyGenerator(req);

    store
      .increment(key, windowMs)
      .then((result) => {
        const now = Date.now();
        const decision = evaluateSlidingWindow({
          result,
          windowMs,
          max,
          now,
        });
        req.rateLimit = { ...decision, key };
        applyRateLimitHeaders(res, decision, now);

        if (decision.allowed) {
          if (onAllowed) onAllowed(req, decision);
          next();
          return;
        }

        res.setHeader('Retry-After', String(decision.retryAfterSeconds));
        if (onRejected) onRejected(req, decision);

        logger.warn('rate_limit_rejected', {
          key,
          route,
          limit: decision.limit,
          windowMs,
          estimatedCount: Number(decision.estimatedCount.toFixed(3)),
          retryAfterSeconds: decision.retryAfterSeconds,
          method: req.method,
          path: req.originalUrl,
        });

        res.status(429).json({
          error: 'rate_limit_exceeded',
          message: `Too many requests. Limit is ${decision.limit} per ${Math.round(
            windowMs / 1000,
          )}s for this endpoint.`,
          retryAfterSeconds: decision.retryAfterSeconds,
        });
      })
      .catch((err: unknown) => {
        // Fail open — availability of the endpoint beats perfect enforcement.
        if (onStoreError) onStoreError(req, err);
        logger.warn('rate_limit_store_failure_failing_open', {
          route,
          store: store.kind,
          error: err instanceof Error ? err.message : String(err),
        });
        next();
      });
  };
}

/**
 * IETF draft `RateLimit-*` headers. Reset is expressed in seconds remaining,
 * matching the draft's delta-seconds form.
 */
export function applyRateLimitHeaders(
  res: Response,
  decision: SlidingWindowDecision,
  now: number = Date.now(),
): void {
  const resetSeconds = Math.max(0, Math.ceil((decision.resetAt - now) / 1000));
  res.setHeader('RateLimit-Limit', String(decision.limit));
  res.setHeader('RateLimit-Remaining', String(decision.remaining));
  res.setHeader('RateLimit-Reset', String(resetSeconds));
}
