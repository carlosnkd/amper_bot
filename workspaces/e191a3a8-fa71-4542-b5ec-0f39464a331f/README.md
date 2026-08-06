# Example Service

A small FastAPI service with a public system router and an authenticated API.

## Running

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Interactive docs: <http://localhost:8000/docs>

## API endpoints

| Method | Path            | Auth        | Description                                                        |
| ------ | --------------- | ----------- | ------------------------------------------------------------------ |
| GET    | `/ping`         | none        | Liveness probe; always returns `200` with `{"pong": true}`.          |
| GET    | `/health`       | none        | Service health check; returns `{"status": "ok"}`.                    |
| GET    | `/api/v1/items` | `X-API-Key` | List items.                                                          |

## Authentication

All routes require the `X-API-Key` header except the public paths listed in
`Settings.public_paths` (`/ping`, `/health`, `/docs`, `/redoc`,
`/openapi.json`). The same whitelist is used by the rate-limiting middleware,
so `/ping` is never throttled.

## Tests

```bash
pytest
```
