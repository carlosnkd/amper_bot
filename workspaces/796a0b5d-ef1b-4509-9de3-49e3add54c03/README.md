# Chat service

Small chat API with a per-user rate limit on `POST /chat`.

## Running the tests

```bash
pip install -r requirements.txt
pytest -q
```

The tests use the in-memory limiter store together with a controllable clock,
so no Redis instance and no `sleep()` calls are required.

## Rate limiting

`POST /chat` is limited to **10 requests per 60 seconds** by default.

* The window is a **sliding** window, not a fixed calendar minute: you cannot
  burst 20 requests around a minute boundary.
* The limit counts **requests**, not messages inside the body.
* Requests rejected by the limiter never reach the model, so they do not
  consume downstream quota.
* The key is the authenticated user (`chat:user:<user_id>`). Anonymous callers
  are keyed by client IP (`chat:ip:<ip>`). With `TRUST_PROXY_HEADERS=true` the
  IP is the first `X-Forwarded-For` entry that is not a configured trusted
  proxy; otherwise it is the socket peer address.
* State lives in Redis when `REDIS_URL` is set, so the limit holds across
  workers and instances. Without `REDIS_URL` an in-process store is used
  (fine for local dev and tests; the limit is then per worker).
* The limiter **fails open**: if Redis is unreachable or the script errors, the
  request is allowed through and a warning is logged (at most once every 30
  seconds, with the count of suppressed occurrences) instead of returning 500.
  The Redis client uses a short (0.25s default) connect/command timeout so a
  hung Redis cannot stall `/chat`.
* Only `POST /chat` is limited; the limiter is not installed globally.

### Response headers

Every `/chat` response (success or rejection) carries:

| Header                  | Meaning                                              |
| ----------------------- | ---------------------------------------------------- |
| `X-RateLimit-Limit`     | Max requests allowed in the window (e.g. `10`)        |
| `X-RateLimit-Remaining` | Requests left in the current window                   |
| `X-RateLimit-Reset`     | Unix timestamp (seconds) when the window frees a slot |

Rejections additionally carry `Retry-After`, in whole seconds.

### 429 response

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 42
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1735689600

{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Too many messages. Try again in 42 seconds."
  }
}
```

### Observability

* Structured warning log `rate_limit_rejected` on each rejection, with
  `endpoint`, `key_type` (`user` or `ip`) and `identifier`.
* Counter metric `rate_limit_rejections_total`, labelled by `endpoint` and
  `key_type` (emitted via `app.metrics`, which forwards to `prometheus_client`
  when it is installed).

## Environment variables

| Variable                         | Default | Description                                                                    |
| -------------------------------- | ------- | ------------------------------------------------------------------------------ |
| `RATE_LIMIT_ENABLED`             | `true`  | Set to `false` to disable enforcement entirely (e.g. locally).                  |
| `RATE_LIMIT_CHAT_MAX_REQUESTS`   | `10`    | Requests allowed per key per window. Positive integer.                          |
| `RATE_LIMIT_CHAT_WINDOW_SECONDS` | `60`    | Sliding window length in seconds. Positive integer.                             |
| `REDIS_URL`                      | *unset* | Redis connection string for shared state. Unset ⇒ in-process store.             |
| `REDIS_TIMEOUT_SECONDS`          | `0.25`  | Redis connect/command timeout in seconds. Positive number.                      |
| `TRUST_PROXY_HEADERS`            | `false` | Read the client IP from `X-Forwarded-For`. Enable only behind your own proxy.   |
| `TRUSTED_PROXIES`                | *empty* | Comma-separated proxy addresses skipped when parsing `X-Forwarded-For`.         |

Invalid values (non-integer, zero or negative) fail fast at startup with a
`ConfigError`.

### Disabling the limiter locally

```bash
export RATE_LIMIT_ENABLED=false
```

or raise the ceiling instead of turning it off:

```bash
export RATE_LIMIT_CHAT_MAX_REQUESTS=1000
```

See [`.env.example`](.env.example) and [`docs/openapi.yaml`](docs/openapi.yaml).

## Layout

```
app/config.py               env-backed settings + validation
app/errors.py               standard JSON error envelope
app/http.py                 minimal request/response/router + test client
app/metrics.py              counter facade (prometheus_client when available)
app/auth.py                 auth context resolution
app/model_client.py         downstream model client
app/ratelimit/store.py      sliding-window stores (Redis Lua + in-memory)
app/ratelimit/limiter.py    policy, fail-open, logging + metrics
app/ratelimit/middleware.py key resolution + endpoint decorator
app/main.py                 app wiring, /chat handler
```
