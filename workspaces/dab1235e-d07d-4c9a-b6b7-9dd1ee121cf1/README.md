# Snippet API

A small FastAPI service, refactored from the original single-file `snippet.py`
into a maintainable package with typed contracts, consistent error handling and
a pytest suite.

## Project layout

```
app/
  __init__.py
  __main__.py          # `python -m app` dev entrypoint
  main.py              # create_app() + ASGI `app` + exception handlers
  api/
    routes.py          # GET /, GET /health, GET /items/{item_id}
    schemas.py         # Pydantic response models
  core/
    config.py          # pydantic-settings Settings (env / .env)
    logging.py         # stdlib logging configured once
  repository/
    items.py           # in-memory item store
run.py                 # thin dev entrypoint (uvicorn.run from Settings)
tests/                 # pytest + TestClient suite
requirements.txt
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Environment variables

Settings are read from the environment or a local `.env` file
(see `.env.example`). Names are case-insensitive.

| Variable      | Default       | Description                                  |
| ------------- | ------------- | -------------------------------------------- |
| `APP_NAME`    | `Snippet API` | Title shown in the OpenAPI docs.             |
| `APP_VERSION` | `1.0.0`       | Version reported by `GET /health`.           |
| `HOST`        | `0.0.0.0`     | Bind address used by the dev entrypoints.    |
| `PORT`        | `8000`        | Bind port used by the dev entrypoints.       |
| `DEBUG`       | `false`       | FastAPI debug mode + uvicorn auto-reload.    |
| `LOG_LEVEL`   | `INFO`        | Root logging level (`DEBUG`, `INFO`, ...).   |

```bash
cp .env.example .env
```

## Run the server

```bash
# recommended (auto-reload during development)
uvicorn app.main:app --reload

# or via the thin entrypoints, which use HOST/PORT/DEBUG from Settings
python run.py
python -m app
```

Interactive docs: <http://localhost:8000/docs>

## Endpoints

| Method | Path               | Response                                       |
| ------ | ------------------ | ---------------------------------------------- |
| GET    | `/`                | `{"message": "Hello, World!"}`                  |
| GET    | `/health`          | `{"status": "ok", "version": "1.0.0"}`          |
| GET    | `/items/{item_id}` | `{"item_id": 1, "q": null}`                     |

`q` is optional and limited to 50 characters. Unknown `item_id`s return `404`.

### Error format

Every error — HTTP exceptions, validation failures and unexpected crashes —
returns the same envelope:

```json
{ "detail": "Item not found", "status_code": 404 }
```

Validation errors put a list of `{loc, msg, type}` objects in `detail`.
Unexpected errors are logged server-side and returned as
`{"detail": "Internal Server Error", "status_code": 500}` with no traceback.

## Run the tests

```bash
pytest              # quiet run, config in pytest.ini
pytest -v           # verbose
```

The suite covers the root and health payloads, `/items/{id}` with and without
`q`, the 404 path, 422 for a non-integer id and for an over-length `q`, and the
generic 500 handler. `tests/conftest.py` provides a `client` fixture and seeds
the in-memory store before each test.

## Migration note

`snippet.py` is now a deprecated shim that re-exports `app.main:app` so old
commands keep working. Use `app.main:app` instead; the shim can be deleted.
