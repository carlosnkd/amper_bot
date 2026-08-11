import sys
from fastapi import FastAPI, Form, Request
from pathlib import Path
from backend.access import check_password, grant_session, inject_gate, read_role
from backend.api.routes import router
from backend.main import init_db
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

# yt_agents (github.com/carlosnkd/yt_agents) lives in its own git repo, nested under
# projects/yt_agents rather than installed as a package -- so its root goes on sys.path
# here (like this app's own repo root is on sys.path for "backend"/"agents" to resolve)
# before importing it, letting its internal absolute imports (`from yt_backend...`,
# `from research_agents...`) resolve as top-level packages found there. Its own backend/
# and agents/ packages were renamed to yt_backend/ and research_agents/ (see that repo's
# git history) specifically so they don't collide with this app's own same-named
# top-level packages once both are imported into the same process.
YT_AGENTS_ROOT = Path(__file__).resolve().parent.parent / "projects" / "yt_agents"
if str(YT_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(YT_AGENTS_ROOT))

from yt_backend.app import app as yt_agents_app  # noqa: E402 -- see sys.path setup above

app = FastAPI(title="Amper API", docs_url="/docs")

# Amper Bot (this app) no longer owns the domain root -- it's one project among
# several showcased on the carlosnakid.com landing page (see serve_landing() below),
# so its UI/API/static assets all live under the /coddy path prefix instead of "/".
# static/index.html and static/js/app.js (API_BASE) were updated to match --
# see those files for the corresponding absolute-path changes.
app.mount("/coddy/static", StaticFiles(directory="static"), name="static")
app.include_router(router, prefix="/coddy")

# Shared password-gate overlay assets (static_gate/gate.css + gate.js), injected
# into the gated pages below via backend/access.py's inject_gate() -- served from
# an absolute top-level path so both /coddy and /yt-agents can reference it
# the same way regardless of which app actually renders their page. See
# backend/access.py for what these assets are and why.
app.mount("/static/gate", StaticFiles(directory="static_gate"), name="gate_assets")

@app.on_event("startup")
def on_startup() -> None:
    # Creates the `call_center_data`, `users`, and `messages` tables (backend/models.py)
    # in backend.db if they don't already exist. Safe to run on every startup.
    init_db()

# ---------------------------------------------------------------------------
# Password gate for the /coddy and /yt-agents project pages.
#
# Neither project should be publicly browsable. The password lives in
# project_password.json (gitignored -- see project_password.example.json for
# the format and edit the real file's value before deploying). Unlike the
# original all-or-nothing gate, a visit now gets one of three states, tracked
# via a signed session cookie (see backend/access.py):
#   - no session  -- the real page is served but blurred behind an overlay
#     (backend/access.py's inject_gate() + static_gate/gate.js) offering
#     "I have a password" (-> POST .../unlock) or "Request a password"
#     (opens a WhatsApp chat to Carlos, and immediately grants guest access
#     below -- no approval step, the WhatsApp message is just the nudge).
#   - "guest"  -- GET .../guest, no password needed. Full page, not blurred,
#     but read-only: mutating calls are 403'd server-side (Coddy's API and
#     yt_agents' API alike, both via require_full() -- backend/api/routes.py
#     and projects/yt_agents/yt_backend/api/routes.py respectively)
#     regardless of what the client does, so this is enforced, not just
#     hidden in the UI.
#   - "full"  -- POST .../unlock with the correct password. Everything.
# The cookie has no Max-Age, so it's a browser-session grant: closing the
# browser means unlocking (or requesting) again next time, same spirit as
# the old "re-enter each visit" gate, just persisted for the session instead
# of every single request.
# ---------------------------------------------------------------------------


def _serve_coddy_page(request: Request, *, error: bool = False) -> HTMLResponse:
    role = read_role(request, "coddy")
    if role == "full" and not error:
        return FileResponse(Path("static/index.html"))
    html_source = Path("static/index.html").read_text(encoding="utf-8")
    html_source = inject_gate(
        html_source,
        project="coddy",
        label="Coddy",
        role=role,
        unlock_url="/coddy/unlock",
        guest_url="/coddy/guest",
        error=error,
    )
    return HTMLResponse(html_source, status_code=401 if error else 200)


@app.get("/coddy", include_in_schema=False)
@app.get("/coddy/", include_in_schema=False)
def gate_coddy(request: Request):
    return _serve_coddy_page(request)


@app.post("/coddy/unlock", include_in_schema=False)
def unlock_coddy(request: Request, password: str = Form(...)):
    if not check_password(password):
        return _serve_coddy_page(request, error=True)
    response = RedirectResponse(url="/coddy", status_code=303)
    grant_session(response, request, "coddy", "full")
    return response


@app.get("/coddy/guest", include_in_schema=False)
def guest_coddy(request: Request):
    response = RedirectResponse(url="/coddy", status_code=303)
    grant_session(response, request, "coddy", "guest")
    return response


YT_AGENTS_INDEX = YT_AGENTS_ROOT / "static" / "index.html"


def _serve_yt_agents_page(request: Request, *, error: bool = False) -> HTMLResponse:
    role = read_role(request, "yt_agents")
    if role == "full" and not error:
        return FileResponse(YT_AGENTS_INDEX)
    html_source = YT_AGENTS_INDEX.read_text(encoding="utf-8")
    html_source = inject_gate(
        html_source,
        project="yt_agents",
        label="Yt Agents",
        role=role,
        unlock_url="/yt-agents/unlock",
        guest_url="/yt-agents/guest",
        error=error,
    )
    return HTMLResponse(html_source, status_code=401 if error else 200)


@app.get("/yt-agents", include_in_schema=False)
@app.get("/yt-agents/", include_in_schema=False)
def gate_yt_agents(request: Request):
    return _serve_yt_agents_page(request)


@app.post("/yt-agents/unlock", include_in_schema=False)
def unlock_yt_agents(request: Request, password: str = Form(...)):
    if not check_password(password):
        return _serve_yt_agents_page(request, error=True)
    response = RedirectResponse(url="/yt-agents", status_code=303)
    grant_session(response, request, "yt_agents", "full")
    return response


@app.get("/yt-agents/guest", include_in_schema=False)
def guest_yt_agents(request: Request):
    response = RedirectResponse(url="/yt-agents", status_code=303)
    grant_session(response, request, "yt_agents", "guest")
    return response


# Registered *after* the gate routes above so the exact "/yt-agents",
# "/yt-agents/", "/yt-agents/unlock", and "/yt-agents/guest" paths hit the
# gate routes first; every other sub-path (e.g. /yt-agents/run,
# /yt-agents/static/...) still falls through to this mount as before.
#
# yt_agents (github.com/carlosnkd/yt_agents) is itself a FastAPI (ASGI) app --
# projects/yt_agents/yt_backend/app.py -- so it's mounted directly, no WSGI<->ASGI
# bridge needed (unlike the old Date Invitation Flask app this replaced). Its own
# "/" route and "/static" mount become "/yt-agents/" and "/yt-agents/static/..."
# once mounted here; static/index.html and static/js/app.js's API_BASE were
# updated to match, same convention as Coddy's own /coddy prefix (see
# static/index.html and static/js/app.js). Whatever env vars its own agents need
# (GOOGLE_API_KEY, SERPER_API_KEY, GOOGLE_APPLICATION_CREDENTIALS, etc. -- see
# projects/yt_agents/research_agents/research/agent.py) must be set wherever this
# service runs, same as this app's own .env.
app.mount("/yt-agents", yt_agents_app)

@app.get("/")
def serve_landing():
    return FileResponse(Path("static/landing.html"))

@app.get("/projects")
def serve_projects():
    return FileResponse(Path("static/projects.html"))

@app.get("/resume.pdf")
def serve_resume():
    return FileResponse(
        Path("CarlosNakidResume.pdf"),
        media_type="application/pdf",
        filename="CarlosNakidResume.pdf",
        content_disposition_type="inline"
    )
