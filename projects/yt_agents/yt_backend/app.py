from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from yt_backend.api.routes import router
from yt_backend.main import init_db

init_db()

# BASE_DIR resolves relative to this file, not the process's working directory,
# so static/index.html and static/ still resolve correctly when this app is
# mounted in-process inside amper_bot's own FastAPI app (backend/app.py),
# whose CWD is the amper_bot repo root, not this project's.
BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Agentic AI API", docs_url="/docs")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(router)

@app.get("/")
def serve_ui():
    return FileResponse(BASE_DIR / "static/index.html")
