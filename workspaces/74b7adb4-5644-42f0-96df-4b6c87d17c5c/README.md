# app

## Configuration

Copy `config.example.json` to `config.json` and/or `.env.example` to `.env`, then adjust.
The full key/type/default/env-var reference lives in [`config/README.md`](config/README.md).

Recently added: a `rate_limit` section (`enabled`, `requests`, `window`). The values are
parsed and validated at startup and exposed as `cfg.RateLimit`, but are **not yet
enforced** — the limiter itself arrives in a follow-up change.
