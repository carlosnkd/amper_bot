# Rate limiting design notes

## Policy

`POST /chat` — **10 requests / 60 seconds**, sliding window, per key.

* Configurable through `RATE_LIMIT_CHAT_MAX_REQUESTS` and
  `RATE_LIMIT_CHAT_WINDOW_SECONDS`; disabled with `RATE_LIMIT_ENABLED=false`.
* Applied to the endpoint only (`app/main.py` wires the decorator onto the
  `POST /chat` route); it is deliberately *not* global middleware.
* Counts requests, not messages in the payload.

## Key resolution (`app/ratelimit/middleware.py`)

| Caller           | Key                     |
| ---------------- | ----------------------- |
| Authenticated    | `chat:user:<user_id>`   |
| Anonymous        | `chat:ip:<client_ip>`   |

`client_ip` returns the first `X-Forwarded-For` entry that is not listed in
`TRUSTED_PROXIES` when `TRUST_PROXY_HEADERS=true`, otherwise the socket peer
address. Untrusted proxy headers are ignored so clients cannot rotate their key
by spoofing `X-Forwarded-For`.

## Store (`app/ratelimit/store.py`)

Single interface:

```python
store.check_and_consume(key, limit, window_seconds) -> RateLimitResult
#   .allowed  .remaining  .retry_after  .reset_at  (+ .limit)
```

### Redis implementation

One `EVALSHA` per request running this Lua body atomically:

1. `ZREMRANGEBYSCORE key 0 now-window` — drop entries older than the window.
2. `ZCARD key` — count what remains.
3. `ZADD key now <unique-member>` — only when `count < limit`.
4. `PEXPIRE key window` — the key self-cleans when a caller goes quiet.
5. `ZRANGE key 0 0 WITHSCORES` — the oldest entry defines `reset_at`.

Because the whole read-modify-write happens inside the script, concurrent
workers cannot both observe `count == limit - 1` and both admit a request.

Members are `"<now_ms>-<uuid4>"` so two requests landing in the same
millisecond are distinct sorted-set members rather than one overwritten score.

### In-memory implementation

Same semantics using a per-key list of timestamps under a lock. Used when
`REDIS_URL` is unset (local dev) and by the tests, which inject a fake clock so
no test ever sleeps. Note it is per-process: with several workers the effective
limit is `limit × workers`. Always set `REDIS_URL` in production.

## Fail-open (`app/ratelimit/limiter.py`)

Any exception from the store (connection refused, timeout, script error,
garbage reply) results in the request being **allowed**. A chat outage is worse
than a briefly unenforced limit. The warning is throttled to one line every
`INFRA_ERROR_LOG_INTERVAL_SECONDS` (30s), and each line reports how many
occurrences were suppressed since the last one. The Redis client is created
with `socket_connect_timeout` and `socket_timeout` set to
`REDIS_TIMEOUT_SECONDS` (0.25s default) so a hung Redis adds at most that much
latency.

## Observability

* `rate_limit_rejected` — structured WARNING with `endpoint`, `key_type`
  (`user`/`ip`), `identifier`, `limit`, `window_seconds`, `retry_after`.
* `rate_limit_store_unavailable` — throttled WARNING when failing open.
* `rate_limit_rejections_total{endpoint,key_type}` — counter emitted through
  `app.metrics`, which forwards to `prometheus_client` if installed and
  otherwise keeps an in-process counter.

## Response contract

Success and rejection both carry `X-RateLimit-Limit`, `X-RateLimit-Remaining`
and `X-RateLimit-Reset`. Rejections are `429` with:

```json
{"error": {"code": "rate_limit_exceeded", "message": "Too many messages. Try again in N seconds."}}
```

plus `Retry-After: N`. The decorator short-circuits before the handler runs, so
no model/downstream call is made for a rejected request.
