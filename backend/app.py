import json
import secrets
from fastapi import FastAPI, Form
from pathlib import Path
from a2wsgi import WSGIMiddleware
from backend.api.routes import router
from backend.main import init_db
from date_invitation.app import app as date_invitation_app
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

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

# ---------------------------------------------------------------------------
# Password gate for the /coddy and /date-invitation project pages.
#
# Neither project should be publicly browsable. The password lives in
# project_password.json (gitignored -- see project_password.example.json for
# the format and edit the real file's value before deploying). There's no
# cookie/session: GET always shows the password form, and a correct POST
# returns the real page for that one response only, so the form reappears on
# the next visit/refresh, exactly like re-entering a locked door each time.
#
# Note this only gates the project's entry page, not every sub-resource --
# static assets and API calls made *by* the page once loaded aren't
# separately password-checked, by the same "gate the visit, not every
# request" design.
# ---------------------------------------------------------------------------
PROJECT_PASSWORD_FILE = Path("project_password.json")


def _load_gate_password() -> str | None:
    try:
        data = json.loads(PROJECT_PASSWORD_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data.get("password") or None


def _check_password(submitted: str) -> bool:
    expected = _load_gate_password()
    if not expected:
        # Fail closed: a missing/unconfigured password file must never mean
        # "let everyone in".
        return False
    return secrets.compare_digest(submitted, expected)


def _gate_page(project_label: str, action: str, error: bool = False) -> HTMLResponse:
    error_html = '<p class="error">Wrong password — try again.</p>' if error else ""
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{project_label} — Password required</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    background: #f5f7fa; color: #101828;
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #0c1220; color: #eef1f6; }}
    .card {{ background: #141c2e !important; border-color: rgba(255,255,255,.09) !important; }}
    input {{ background: #182238 !important; border-color: rgba(255,255,255,.16) !important; color: #eef1f6 !important; }}
  }}
  .card {{
    width: 100%; max-width: 340px; padding: 32px; border-radius: 14px;
    background: #fff; border: 1px solid #e2e7ef; box-shadow: 0 10px 24px rgba(16,24,40,.1);
    text-align: center; box-sizing: border-box;
  }}
  h1 {{ font-size: 17px; margin: 0 0 6px; }}
  p.sub {{ margin: 0 0 20px; font-size: 13.5px; color: #64748b; }}
  input {{
    width: 100%; box-sizing: border-box; padding: 10px 12px; border-radius: 8px;
    border: 1px solid #d3dae5; font-size: 14px; margin-bottom: 12px;
  }}
  button {{
    width: 100%; padding: 10px 12px; border-radius: 8px; border: 0; cursor: pointer;
    background: #0b2f5e; color: #fff; font-size: 14px; font-weight: 600;
  }}
  button:hover {{ background: #0f3d78; }}
  p.error {{ margin: 0 0 12px; font-size: 13px; color: #d33; font-weight: 600; }}
</style>
</head>
<body>
  <div class="card">
    <h1>{project_label}</h1>
    <p class="sub">This project is private. Enter the password to continue.</p>
    {error_html}
    <form method="post" action="{action}">
      <input type="password" name="password" placeholder="Password" autofocus required />
      <button type="submit">Enter</button>
    </form>
  </div>
</body>
</html>"""
    return HTMLResponse(html, status_code=401 if error else 200)


@app.get("/coddy", include_in_schema=False)
@app.get("/coddy/", include_in_schema=False)
def gate_coddy():
    return _gate_page("Coddy", "/coddy")


@app.post("/coddy", include_in_schema=False)
@app.post("/coddy/", include_in_schema=False)
def unlock_coddy(password: str = Form(...)):
    if not _check_password(password):
        return _gate_page("Coddy", "/coddy", error=True)
    return FileResponse(Path("static/index.html"))


@app.get("/date-invitation", include_in_schema=False)
@app.get("/date-invitation/", include_in_schema=False)
def gate_date_invitation():
    return _gate_page("Date Invitation", "/date-invitation")


@app.post("/date-invitation", include_in_schema=False)
@app.post("/date-invitation/", include_in_schema=False)
def unlock_date_invitation(password: str = Form(...)):
    if not _check_password(password):
        return _gate_page("Date Invitation", "/date-invitation", error=True)
    # Render through Flask itself (not a raw template read) so url_for(...)
    # calls in the template resolve, with SCRIPT_NAME forced to match the
    # /date-invitation mount below so those URLs come out correctly prefixed.
    resp = date_invitation_app.test_client().get(
        "/", environ_overrides={"SCRIPT_NAME": "/date-invitation"}
    )
    return HTMLResponse(resp.get_data(as_text=True), status_code=resp.status_code)


# Registered *after* the gate routes above so the exact "/date-invitation"
# and "/date-invitation/" paths hit the gate first; every other sub-path
# (e.g. /date-invitation/submit, /date-invitation/static/...) still falls
# through to this mount as before.
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
        as_attachment=False
    )
