from fastapi import FastAPI
from pathlib import Path
from backend.api.routes import router
from backend.main import init_db
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="Amper API", docs_url="/docs")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)


@app.on_event("startup")
def on_startup() -> None:
    # Creates the `call_center_data`, `users`, and `messages` tables (backend/models.py)
    # in backend.db if they don't already exist. Safe to run on every startup.
    init_db()

@app.get("/")
def serve_ui():
    return FileResponse(Path("static/index.html"))
