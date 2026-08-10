from fastapi import FastAPI
from pathlib import Path
from backend.api.routes import router
from backend.main import init_db
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="Amper API", docs_url="/docs")

# Amper Bot (this app) no longer owns the domain root -- it's one project among
# several showcased on the carlosnakid.com landing page (see serve_landing() below),
# so its UI/API/static assets all live under the /coddy path prefix instead of "/".
# static/index.html and static/js/app.js (API_BASE) were updated to match --
# see those files for the corresponding absolute-path changes.
app.mount("/coddy/static", StaticFiles(directory="static"), name="static")
app.include_router(router, prefix="/coddy")


@app.on_event("startup")
def on_startup() -> None:
    # Creates the `call_center_data`, `users`, and `messages` tables (backend/models.py)
    # in backend.db if they don't already exist. Safe to run on every startup.
    init_db()

@app.get("/")
def serve_landing():
    return FileResponse(Path("static/landing.html"))

@app.get("/resume.pdf")
def serve_resume():
    return FileResponse(
        Path("CarlosNakidResume.pdf"),
        media_type="application/pdf",
        filename="CarlosNakidResume.pdf",
    )

@app.get("/coddy")
@app.get("/coddy/")
def serve_ui():
    return FileResponse(Path("static/index.html"))
