from fastapi import FastAPI
from pathlib import Path
from backend.api.routes import router
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="Amper API", docs_url="/docs")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)

@app.get("/")
def serve_ui():
    return FileResponse(Path("static/index.html"))
