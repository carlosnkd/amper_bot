# rate-limited-items-api

A small Express + TypeScript API whose **creation endpoint is rate limited**. Everything
else is unlimited by construction.

| Route                | Limited? | Notes                                              |
| -------------------- | -------- | -------------------------------------------------- |
| `POST /api/items`    | **yes**  | Sliding-window counter, per API key or client IP   |
| `GET /api/items`     | no       | Reads are unlimited                                |
| `GET /healthz`       | no       | Liveness probe, reports the active limiter store   |
| `GET /internal/metrics` | no    | Allowed vs rejected creation counters              |

## Quick start

```bash
npm install
cp .env.example .env
npm run dev                  # in-memory limiter store
docker compose up -d redis   # optional: shared store across instances
REDIS_URL=redis://127.0.0.1:6379 npm run dev
```

```bash
npm run build   # tsc -> dist/
npm start       # run the built server
npm test        # jest (memory store only)
npm run test:redis   # boots the compose Redis and runs the suite against both stores
npm run lint
```

## How the limiter works

**Algorithm — sliding-window counter.** Time is split into fixed buckets of `windowMs`.
Each request `INCR`s the bucket it lands in; the estimated load for the trailing window is

```
estimated = current_bucket + previous_bucket * (fraction of the current bucket not yet elapsed)
```

A request is allowed while `estimated <= max`. This avoids the classic fixed-window
burst-at-boundary hole (spending a full budget at `t = window - 1ms` and another full
budget 2ms later) without any per-request token bookkeeping. See
`src/ratelimit/slidingWindow.ts`.

**Client identity.** `X-API-Key` when present, otherwise the client IP. There is no
user/session auth in this codebase yet, so an API key is the only notion of identity.
API keys are HMAC-SHA256 hashed (salted with `RATE_LIMIT_KEY_SALT`) **before** they are
used as a store key or written to a log line, so raw keys never leave the process.
IP resolution goes through Express' `req.ip`, which honours `trust proxy` — set
`TRUST_PROXY_HOPS` to the number of proxies actually in front of the app so a client
cannot spoof `X-Forwarded-For` and mint itself a fresh budget.

**Store keys are namespaced by route** (`POST:/api/items|key:<hash>`), so reusing the
limiter on another endpoint later gives that endpoint its own budget.

**No queueing.** Over-limit requests get an immediate `429`; nothing is delayed.

## Response contract

Every response produced by the limited endpoint carries the IETF draft headers:

```
RateLimit-Limit: 10
RateLimit-Remaining: 7
RateLimit-Reset: 42          # seconds until the current window rolls over
```

Rejections add `Retry-After` (seconds) and this body:

```json
{
  "error": "rate_limit_exceeded",
  "message": "Too many requests. Limit is 10 per 60s for this endpoint.",
  "retryAfterSeconds": 42
}
```

Trusted keys (see below) skip the limiter entirely and therefore carry **no**
`RateLimit-*` headers.

The limiter is mounted ahead of body validation, so malformed floods still consume quota
instead of being a free way to hammer the API.

## Redis vs in-memory

| `REDIS_URL` | Store                      | Behaviour                                        |
| ----------- | -------------------------- | ------------------------------------------------ |
| set         | `RedisRateLimitStore`      | Counters shared by all app instances             |
| unset       | `MemoryRateLimitStore`     | Per-process counters; local dev and tests        |

The Redis store performs the increment, the previous-bucket read and the TTL set in a
single atomic Lua script (`src/ratelimit/redisStore.ts`), so concurrent requests across
instances cannot both read a pre-increment count and slip past the limit. Buckets are
given a TTL of two windows so the previous bucket is still readable after rollover, and
expire on their own — nothing to clean up. The in-memory store expires entries lazily on
read plus a periodic sweep, so it cannot grow without bound.

If `ioredis` cannot be loaded or the URL is unusable, the factory logs a warning and
falls back to the in-memory store rather than failing startup.

## Fail-open policy

If the store errors at request time (Redis unreachable, script failure, timeout) the
limiter **allows the request**, increments `rate_limit_store_errors_total` and logs
`rate_limit_store_failure_failing_open`. Availability of the endpoint is considered more
important than perfect enforcement during an infrastructure outage. Watch that counter —
a non-zero rate means the limit is not being enforced.

## Observability

Every rejection emits one structured JSON line:

```json
{"ts":"...","level":"warn","msg":"rate_limit_rejected","key":"POST:/api/items|key:9f3c…",
 "route":"POST:/api/items","limit":10,"windowMs":60000,"estimatedCount":11,
 "retryAfterSeconds":37,"method":"POST","path":"/api/items"}
```

The `key` field contains only the hashed identity. Counters are available at
`GET /internal/metrics`:

- `items_create_allowed_total`
- `items_create_rejected_total`
- `rate_limit_store_errors_total`

## Environment variables

| Variable                  | Default           | Meaning                                                    |
| ------------------------- | ----------------- | ---------------------------------------------------------- |
| `PORT`                    | `3000`            | HTTP port                                                  |
| `TRUST_PROXY_HOPS`        | `0`               | Proxy hops to trust when resolving the client IP           |
| `RATE_LIMIT_WINDOW_MS`    | `60000`           | Trailing window length for `POST /api/items`               |
| `RATE_LIMIT_MAX`          | `10`              | Max creations per client per window                         |
| `RATE_LIMIT_TRUSTED_KEYS` | *(empty)*         | Comma-separated raw API keys that bypass the limiter        |
| `RATE_LIMIT_KEY_SALT`     | `local-dev-salt`  | HMAC salt for hashing API keys — **set this in production** |
| `REDIS_URL`               | *(unset)*         | When set, counters live in Redis                            |

Invalid or non-positive numeric values fall back to the default.

## Applying the limiter to another route

The limiter is ordinary Express middleware, so it drops onto a single handler:

```ts
import { rateLimit } from './ratelimit/middleware';
import { makeKeyGenerator } from './ratelimit/identity';

const widgetsLimiter = rateLimit({
  store,                       // reuse the app's store
  windowMs: 60_000,
  max: 30,
  route: 'POST:/api/widgets',  // own namespace => own budget
  keyGenerator: makeKeyGenerator({ route: 'POST:/api/widgets', salt: config.keySalt }),
});

router.post('/widgets', widgetsLimiter, validateWidget, createWidgetHandler);
```

To reuse the *creation* endpoint's exact configuration (trusted-key bypass and metrics
included) call `createItemsRateLimiter({ store, route: 'POST:/api/widgets' })` from
`src/ratelimit/createItemsLimiter.ts`.

## Layout

```
src/
  app.ts                      Express wiring; limiter applied to POST /api/items only
  server.ts                   HTTP listener + graceful shutdown
  logger.ts, metrics.ts       Structured JSON logging, in-process counters
  items/                      Repository, router, body validation
  ratelimit/
    store.ts                  Store interface + bucket maths
    memoryStore.ts            In-process store with lazy expiry
    redisStore.ts             Atomic Lua-script store
    storeFactory.ts           Picks Redis when REDIS_URL is set
    slidingWindow.ts          The allow/deny decision
    middleware.ts             rateLimit() Express middleware, headers, 429, fail-open
    identity.ts               API-key hashing / trust-proxy-aware IP / key generator
    config.ts                 The single limit, env-overridable
    createItemsLimiter.ts     The configured limiter for POST /api/items
tests/
  ratelimit/                  Unit tests
  integration/                supertest end-to-end tests (run against both stores)
  helpers/stores.ts           Store matrix; Redis skipped when unavailable
```
