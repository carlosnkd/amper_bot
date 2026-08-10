from fastapi import FastAPI, Form, Request
from pathlib import Path
from a2wsgi import WSGIMiddleware
from backend.access import check_password, grant_session, inject_gate, read_role
from backend.api.routes import router
from backend.main import init_db
from date_invitation.app import app as date_invitation_app
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

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
# an absolute top-level path so both /coddy and /date-invitation can reference it
# the same way regardless of which app actually renders their page. See
# backend/access.py for what these assets are and why.
app.mount("/static/gate", StaticFiles(directory="static_gate"), name="gate_assets")

@app.on_event("startup")
def on_startup() -> None:
    # Creates the `call_center_data`, `users`, and `messages` tables (backend/models.py)
    # in backend.db if they don't already exist. Safe to run on every startup.
    init_db()

# ---------------------------------------------------------------------------
# Password gate for the /coddy and /date-invitation project pages.
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
#     but read-only: mutating calls are 403'd server-side (Coddy's API --
#     backend/api/routes.py's require_full(); Date Invitation's /submit --
#     date_invitation/app.py's before_request guard) regardless of what the
#     client does, so this is enforced, not just hidden in the UI.
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


def _render_date_invitation_html() -> str:
    # Render through Flask itself (not a raw template read) so url_for(...)
    # calls in the template resolve, with SCRIPT_NAME forced to match the
    # /date-invitation mount below so those URLs come out correctly prefixed.
    resp = date_invitation_app.test_client().get(
        "/", environ_overrides={"SCRIPT_NAME": "/date-invitation"}
    )
    return resp.get_data(as_text=True)


def _serve_date_invitation_page(request: Request, *, error: bool = False) -> HTMLResponse:
    role = read_role(request, "date_invitation")
    html_source = _render_date_invitation_html()
    if role == "full" and not error:
        return HTMLResponse(html_source)
    html_source = inject_gate(
        html_source,
        project="date_invitation",
        label="Date Invitation",
        role=role,
        unlock_url="/date-invitation/unlock",
        guest_url="/date-invitation/guest",
        error=error,
    )
    return HTMLResponse(html_source, status_code=401 if error else 200)


@app.get("/date-invitation", include_in_schema=False)
@app.get("/date-invitation/", include_in_schema=False)
def gate_date_invitation(request: Request):
    return _serve_date_invitation_page(request)


@app.post("/date-invitation/unlock", include_in_schema=False)
def unlock_date_invitation(request: Request, password: str = Form(...)):
    if not check_password(password):
        return _serve_date_invitation_page(request, error=True)
    response = RedirectResponse(url="/date-invitation", status_code=303)
    grant_session(response, request, "date_invitation", "full")
    return response


@app.get("/date-invitation/guest", include_in_schema=False)
def guest_date_invitation(request: Request):
    response = RedirectResponse(url="/date-invitation", status_code=303)
    grant_session(response, request, "date_invitation", "guest")
    return response


# Registered *after* the gate routes above so the exact "/date-invitation",
# "/date-invitation/", "/date-invitation/unlock", and "/date-invitation/guest"
# paths hit the gate routes first; every other sub-path (e.g.
# /date-invitation/submit, /date-invitation/static/...) still falls through
# to this mount as before.
#
# Date Invitation is a separate Flask (WSGI) app -- date_invitation/app.py, copied in
# from github.com/carlosnkd/date-invitation -- mounted in-process rather than proxied
# to a second service, since it's small and dependency-free enough not to warrant its
# own deployment. a2wsgi bridges WSGI<->ASGI and sets SCRIPT_NAME on the way in, so
# Flask's own `url_for('static', ...)` calls in its templates already emit correctly
# prefixed URLs (e.g. /date-invitation/static/css/style.css) with no template changes.
# Its email-sending env vars (SMTP_*/MAILGUN_*, see date_invitation/.env.example) must
# be set wherever this service runs -- they're not committed, same as this app's own .env.
app.mount("/date-invitation", WSGIMiddleware(date_invitation_app))

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
