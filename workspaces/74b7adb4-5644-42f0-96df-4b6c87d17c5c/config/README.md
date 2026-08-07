# Configuration reference

Configuration is resolved from three layers, later layers overriding earlier ones:

1. **Built-in defaults** — see `Default()` in `config/config.go`.
2. **Config file** — JSON, `config.json` by default (override the path with `APP_CONFIG_FILE`). See [`config.example.json`](../config.example.json).
3. **Environment variables** — see [`.env.example`](../.env.example).

Everything is validated once at startup. A bad value aborts boot with an error naming
the offending key and its environment variable, e.g.:

```
config: invalid value for "rate_limit.requests" (env RATE_LIMIT_REQUESTS): 0: must be a positive integer
```

Durations use Go's duration syntax: `500ms`, `30s`, `5m`, `1h`.

## Server

| Key | Type | Default | Env var |
| --- | --- | --- | --- |
| `server.host` | string | `0.0.0.0` | `SERVER_HOST` |
| `server.port` | int | `8080` | `SERVER_PORT` |
| `server.read_timeout` | duration | `15s` | `SERVER_READ_TIMEOUT` |

## Database

| Key | Type | Default | Env var |
| --- | --- | --- | --- |
| `database.url` | string | `postgres://localhost:5432/app?sslmode=disable` | `DATABASE_URL` |
| `database.max_open_conns` | int | `10` | `DATABASE_MAX_OPEN_CONNS` |

## Logging

| Key | Type | Default | Env var |
| --- | --- | --- | --- |
| `log.level` | string (`debug`\|`info`\|`warn`\|`error`) | `info` | `LOG_LEVEL` |

## Rate limiting

> **Not yet enforced.** These values are read, parsed and validated at startup and
> exposed as `cfg.RateLimit`, but no limiter consumes them yet — enforcement arrives in a
> follow-up change. Setting them today changes no request-handling behaviour.

| Key | Type | Default | Env var | Notes |
| --- | --- | --- | --- | --- |
| `rate_limit.enabled` | bool | `false` | `RATE_LIMIT_ENABLED` | Master on/off switch. Defaults to off so existing deployments are unaffected. |
| `rate_limit.requests` | int | `100` | `RATE_LIMIT_REQUESTS` | Max requests allowed per window. Must be a positive integer. |
| `rate_limit.window` | duration | `1m` | `RATE_LIMIT_WINDOW` | Length of the window. Must parse to a non-zero, positive duration. |

This is a single **global** policy: there are no per-route or per-route-group overrides
yet. The schema is intentionally flat so per-endpoint policies can be layered on later
without breaking existing keys.

`requests` and `window` are validated even when `enabled` is `false`, so turning the
limiter on later can never fail on a value that was wrong all along.

Example:

```json
{
  "rate_limit": {
    "enabled": false,
    "requests": 100,
    "window": "1m"
  }
}
```

Reading it from Go:

```go
cfg, err := config.Load("")
if err != nil {
    log.Fatal(err)
}

if cfg.RateLimit.Enabled {
    // Future limiter: budget is cfg.RateLimit.Requests per cfg.RateLimit.Window.
    limiter := ratelimit.New(cfg.RateLimit.Requests, cfg.RateLimit.Window)
    _ = limiter
}
```
