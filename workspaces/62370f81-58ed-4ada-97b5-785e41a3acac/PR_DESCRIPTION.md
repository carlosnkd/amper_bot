# Add `GET /health` liveness probe

## T1 — Findings: entrypoint, router layout, global wrappers

Investigated the backend before wiring anything:

| Question | Finding |
| --- | --- |
| Entrypoint | `app/main.py`, which exposes `create_app(settings)` and a module-level `app = create_app()`. |
| Router layout | Router-per-concern under `app/api/routers/` (`items.py`, now `health.py`); each module exposes a module-level `router = APIRouter(...)` that `main.py` includes. |
| Versioning | Business routers are included with `prefix=settings.api_v1_prefix` (`/api/v1`). The prefix is applied at `include_router` time in `main.py`, not baked into the routers, so a router can opt out simply by being included without it. |
| Global auth | `app.core.security.require_api_key` (header `X-API-Key`). It is **not** attached to the `FastAPI(...)` constructor; it is attached per-include via `dependencies=[Depends(require_api_key)]` on the versioned group. |
| Rate limiting | `app.core.middleware.RateLimitMiddleware` — fixed window, per client IP, applied app-wide as middleware (so it cannot be dodged by router placement alone; it needs a skip list). |
| Request logging | `app.core.middleware.RequestLoggingMiddleware`, also app-wide. |

Consequence for the wiring choices below: auth can be avoided structurally
(include the router outside the authenticated group), but rate limiting and
logging are middleware and therefore need an explicit path exemption.

## T2 — Health router

`app/api/routers/health.py` defines `GET /health`:

* Returns HTTP 200 with body `{"status": "ok"}`.
* No path params, query params or request body.
* Explicit Pydantic response model `HealthResponse` with a single
  `status: Literal["ok"]` field, set via `response_model=`, so OpenAPI shows
  the real schema instead of a bare object.
* Tagged `health`, summary `Liveness probe`.
* **Zero dependencies** — no DB session, no cache, no downstream call. The
  handler is a pure function, so it keeps answering 200 while dependencies are
  down. This is a shallow *liveness* check by design; a deep readiness check
  would be a separate `/ready` endpoint.

## T3 — Wiring (additive only)

In `app/main.py`:

```python
# Public, unversioned, unauthenticated.
app.include_router(health_router)              # -> exactly /health

# Versioned + authenticated API (unchanged behaviour).
app.include_router(items_router,
                   prefix=settings.api_v1_prefix,
                   dependencies=[Depends(require_api_key)])
```

* No prefix and no `dependencies=[...]` on the health include, so the final
  path is exactly `/health` and probes need no credentials.
* `Settings.public_paths` (`/health`, `/docs`, `/redoc`, `/openapi.json`) is
  the single skip list consulted by `RateLimitMiddleware` (never 429 a probe —
  that would get a healthy pod killed under load) and by
  `RequestLoggingMiddleware` (keeps probe spam out of the logs).
* `require_api_key` additionally short-circuits on public paths as a
  belt-and-braces guard in case it is ever attached higher up the tree.
* No existing route's path, prefix, auth or rate-limit behaviour changed.

## T4 — Tests

`tests/test_health.py` (pytest + `fastapi.testclient.TestClient`):

* 200 and exactly `{"status": "ok"}`.
* Succeeds with no auth header, and with a bogus API key; paired with an
  assertion that `/api/v1/items` still 401s unauthenticated, so the test proves
  an *exemption* rather than auth being off.
* `POST/PUT/PATCH/DELETE /health` → 405.
* DB dependency overridden to raise: the DB-backed route blows up, `/health`
  still returns 200.
* `/api/v1/health` → 404 (confirms no version prefix).
* Route introspection: `/health` carries no dependencies.
* `/health` never rate limited even past the limit; `/api/v1/items` still is.

## T5 — OpenAPI and ops surface

* `test_health_in_openapi_schema_under_health_tag` asserts `/health` appears in
  `app.openapi()` under the `health` tag with the `Liveness probe` summary and
  a `$ref`'d response schema containing `status`.
* `Dockerfile`: `HEALTHCHECK` hits `http://127.0.0.1:8000/health`.
* `docker-compose.yml`: service `healthcheck` uses the same path.
* `deploy/k8s/deployment.yaml`: `livenessProbe` and `startupProbe` both use
  `httpGet /health` on the `http` port.
