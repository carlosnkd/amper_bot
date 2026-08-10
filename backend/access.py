"""
Password-gate session helpers, shared by backend/app.py (Coddy + Date
Invitation entry routes), backend/api/routes.py (Coddy's API), and
date_invitation/app.py (its /submit route).

Two access levels per gated project ("coddy", "date_invitation"):
  - "full"  -- granted by POST .../unlock after the correct password (see
    project_password.json / check_password()). Full use of the project.
  - "guest" -- granted by GET .../guest, no password required (the "Request a
    password" button in the injected gate overlay -- see static_gate/gate.js
    -- which also opens a WhatsApp chat to the owner asking for the real
    one). Guests can look around but not mutate anything; which routes count
    as "mutating" is decided per project via require_full()/require_any()
    below (Coddy: backend/api/routes.py: Date Invitation:
    date_invitation/app.py's before_request guard).

Both levels live in a signed (HS256/JWT), project-scoped, HttpOnly session
cookie -- not a server-side session store, since there's nothing worth
persisting past the browser session and no DB dependency for something this
low-stakes. Signed so a visitor can't hand-edit the cookie in devtools to
promote themselves from guest to full; decode_role() rejects anything whose
signature doesn't check out. No Max-Age is set on the cookie itself, so it's
dropped when the browser closes (re-enter each new browser session, like the
old plain password form); the JWT's own `exp` is just a belt-and-suspenders
cap in case a browser/extension keeps it around longer than that anyway.
"""
import json
import re
import secrets
import time
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote

import jwt
from fastapi import HTTPException, Request
from starlette.responses import Response

Role = Literal["guest", "full"]

PROJECT_PASSWORD_FILE = Path("project_password.json")
SESSION_TTL_SECONDS = 12 * 60 * 60
_COOKIE_PREFIX = "access_"

# Carlos's WhatsApp -- "Request a password" opens a wa.me chat here with a
# prefilled message, rather than the server sending anything itself (no
# WhatsApp Business API/credentials involved).
WHATSAPP_NUMBER = "522383886355"

# ?v= cache-busts these on every edit (same convention as static/index.html's
# app.css?v=2/app.js?v=3) -- StaticFiles serves gate.css/gate.js with no
# special cache headers, so without a version bump here, browsers that already
# cached an older copy (e.g. from before a styling change) can keep serving
# it indefinitely. Bump this whenever gate.css or gate.js changes.
_GATE_ASSET_VERSION = 4
GATE_CSS_URL = f"/static/gate/gate.css?v={_GATE_ASSET_VERSION}"
GATE_JS_URL = f"/static/gate/gate.js?v={_GATE_ASSET_VERSION}"


def _load_gate_config() -> dict:
    try:
        return json.loads(PROJECT_PASSWORD_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def check_password(submitted: str) -> bool:
    expected = _load_gate_config().get("password") or None
    if not expected:
        # Fail closed: a missing/unconfigured password file must never mean
        # "let everyone in".
        return False
    return secrets.compare_digest(submitted, expected)


def _session_secret() -> str:
    """Signing key for the access cookies below -- auto-generated into
    project_password.json on first use and persisted there (gitignored, same
    as the password itself) so it survives restarts, but no two deployments
    ever share one by accident."""
    config = _load_gate_config()
    secret = config.get("session_secret")
    if secret:
        return secret
    secret = secrets.token_hex(32)
    config["session_secret"] = secret
    try:
        PROJECT_PASSWORD_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    except OSError:
        pass  # worst case: a fresh secret (and a forced re-login) on next restart
    return secret


def cookie_name(project: str) -> str:
    return f"{_COOKIE_PREFIX}{project}"


def grant_session(response: Response, request: Request, project: str, role: Role) -> None:
    token = jwt.encode(
        {"project": project, "role": role, "exp": int(time.time()) + SESSION_TTL_SECONDS},
        _session_secret(),
        algorithm="HS256",
    )
    response.set_cookie(
        cookie_name(project),
        token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


def decode_role(token: Optional[str], project: str) -> Optional[Role]:
    """Framework-agnostic half of role reading -- takes the raw cookie value
    (however the caller got it: FastAPI's request.cookies, Flask's
    request.cookies, ...) and returns the role it grants for `project`, or
    None if it's missing, unsigned/tampered, expired, or for another
    project."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, _session_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("project") != project:
        return None
    role = payload.get("role")
    return role if role in ("guest", "full") else None


def read_role(request: Request, project: str) -> Optional[Role]:
    return decode_role(request.cookies.get(cookie_name(project)), project)


def require_any(project: str):
    """FastAPI dependency: any granted session (guest or full) required."""

    def _dep(request: Request) -> Role:
        role = read_role(request, project)
        if role is None:
            raise HTTPException(status_code=403, detail="Locked -- unlock this project first.")
        return role

    return _dep


def require_full(project: str):
    """FastAPI dependency: only a "full" (password-unlocked) session may proceed."""

    def _dep(request: Request) -> Role:
        role = read_role(request, project)
        if role != "full":
            raise HTTPException(
                status_code=403,
                detail="Read-only guest access -- enter the password to do this.",
            )
        return role

    return _dep


def _whatsapp_url(project_label: str) -> str:
    text = f"Hi Carlos! I'd like the password for {project_label}."
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(text)}"


def inject_gate(
    html_source: str,
    *,
    project: str,
    label: str,
    role: Optional[Role],
    unlock_url: str,
    guest_url: str,
    error: bool = False,
) -> str:
    """
    Splices the password-gate overlay (static_gate/gate.css + gate.js) into an
    already-rendered project page, rather than swapping in a separate "locked"
    page -- so the real UI is visible-but-blurred (locked) or fully visible
    with a read-only banner (guest) behind the gate. See backend/app.py's
    gate_*/unlock_*/guest_* routes for the callers, and static_gate/gate.js
    for what actually reacts to the injected config.

    Only meant to be called when `role` isn't "full" -- callers serve the
    untouched page directly in that case (see backend/app.py).
    """
    config = {
        "project": project,
        "label": label,
        "role": role,
        "whatsapp": _whatsapp_url(label),
        "unlockUrl": unlock_url,
        "guestUrl": guest_url,
        "error": error,
        "showPasswordForm": error,
    }
    head_inject = f'<link rel="stylesheet" href="{GATE_CSS_URL}" />'
    body_inject = (
        f"<script>window.__GATE__ = {json.dumps(config)};</script>"
        f'<script src="{GATE_JS_URL}"></script>'
    )
    html_source = html_source.replace("</head>", f"{head_inject}</head>", 1)
    # Insert right after the opening <body ...> tag, whatever attributes it has,
    # so gate.js's fetch() lockdown (guest mode) is installed before the page's
    # own script(s) further down ever get a chance to make a request. Replacement
    # passed as a function (not a r"\1..." string) so nothing in body_inject can
    # ever be misread as a backreference.
    html_source = re.sub(
        r"<body[^>]*>", lambda m: m.group(0) + body_inject, html_source, count=1
    )
    return html_source
