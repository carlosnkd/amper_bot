import asyncio
import json
import logging
import queue
import uuid
from pathlib import Path
from backend.access import require_any, require_full
from backend.main import get_db
from fastapi import APIRouter, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from typing import Optional
from agents.common.errors import friendly_error_message
from backend.services.research import build_from_plan, build_from_plan_worker, revise_plan, start_plan
from sqlalchemy.orm import Session
from backend.services.chat import (
    record_message,
    end_conversation,
    load_user_history,
    delete_conversation,
    get_trace,
)
from agents.ticket_pipeline.main import run_ticket_pipeline
from agents.ticket_pipeline.flow import WORKSPACES_ROOT
from agents.ticket_pipeline.tools import resolve_in_workspace

# Every route in this router lives under the /coddy prefix (see
# backend/app.py's app.include_router(router, prefix="/coddy")), so a single
# router-wide dependency enforces "at least a granted session (guest or
# full)" for everything here. Individual mutating routes below additionally
# require "full" via _require_full -- see backend/access.py for what those
# levels mean and static_gate/gate.js for the client-side UX around the same
# restriction (the actual enforcement is here, not there).
router = APIRouter(dependencies=[Depends(require_any("coddy"))])
_require_full = Depends(require_full("coddy"))
logger = logging.getLogger(__name__)

# repo root -- routes.py is backend/api/routes.py, so two parents up.
README_PATH = Path(__file__).resolve().parents[2] / "README.md"
RETRO_PATH = Path(__file__).resolve().parents[2] / "WHAT_I_WOULD_DO_DIFFERENTLY.md"

# Cap on how much of an uploaded file's text we fold into the prompt -- keeps a huge
# attachment from blowing the LLM's context window/cost on a single turn. Chars, not
# bytes, since this is applied post-decode.
MAX_ATTACHMENT_CHARS = 20_000

# Tried in order until one succeeds. utf-8-sig first so a BOM (common from Windows editors
# that "Save As UTF-8") doesn't leak a literal ﻿ into the prompt. cp1252 last as the
# permissive catch-all: it's Windows' historical default for plain-text saves ("ANSI" in
# Notepad et al.) and, unlike utf-8, never raises -- any byte string decodes under it -- so
# it MUST stay last, after real binary formats have already been ruled out by magic bytes
# below, or PDFs/images would "successfully" decode into mojibake instead of being skipped.
_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252")

# Magic-byte prefixes for formats we can't extract text from yet (no PDF/OOXML/image
# parser here) -- checked before the cp1252 catch-all so these get a clear "can't read
# this yet" note instead of cp1252 happily decoding their binary bytes into garbage text.
_BINARY_SIGNATURES = {
    b"%PDF": "PDF",
    b"PK\x03\x04": "zip-based (docx/xlsx/pptx/zip)",
    b"\x89PNG": "PNG image",
    b"\xff\xd8\xff": "JPEG image",
    b"GIF8": "GIF image",
}


def _sniff_binary_kind(raw: bytes) -> Optional[str]:
    for signature, kind in _BINARY_SIGNATURES.items():
        if raw.startswith(signature):
            return kind
    return None


async def _extract_attachment(file: UploadFile) -> dict:
    """
    Reads an uploaded file ONCE and returns a single structured record describing it:
    {"name", "readable", "text", "truncated", "kind"}. This is the one source of truth
    fed to three different consumers, so the file is never re-decoded (and can't drift
    between them):
      1. _attachment_prompt_block() -- folds it into the query text the Planner/Intent
         classifier sees (see _apply_attachment(), used by /run and /run/stream).
      2. record_message()'s `attachments` -- persisted as-is alongside the chat message
         (see backend/services/chat.py), so GET /get_history can replay it back out.
      3. The frontend's file-pane viewer -- reads that persisted record (via #2) to show
         the attachment's content again on a later page load/conversation reopen, exactly
         like it renders the Coder's own generated files.

    Tries utf-8-sig/utf-8/cp1252 in turn (see _TEXT_ENCODINGS) rather than requiring
    strict UTF-8 -- plenty of real-world text files (e.g. a .py saved by a Windows editor
    with a smart quote or em-dash in it) are valid text but not valid UTF-8, and were
    getting dropped entirely before this. Recognized binary formats (PDF, images,
    zip-based Office docs) are named explicitly (`kind`) rather than decoded -- there's no
    OCR/extraction step here. `readable` is False whenever `text` is None, whether because
    the format was recognized-but-binary (`kind` set) or just plain undecodable
    (`kind` None) -- either way there's nothing to show, only the two differ in *why*.
    Truncates very large text files to MAX_ATTACHMENT_CHARS so one attachment can't
    dominate the prompt (or bloat the persisted row) on its own.
    """
    raw = await file.read()
    name = file.filename or "attachment"

    binary_kind = _sniff_binary_kind(raw)
    if binary_kind:
        logger.info("Attachment %r is a %s -- no text extraction available yet", name, binary_kind)
        return {"name": name, "readable": False, "text": None, "truncated": False, "kind": binary_kind}

    text = None
    for encoding in _TEXT_ENCODINGS:
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        logger.warning("Attachment %r couldn't be decoded as text -- treating as unreadable", name)
        return {"name": name, "readable": False, "text": None, "truncated": False, "kind": None}

    truncated = len(text) > MAX_ATTACHMENT_CHARS
    if truncated:
        text = text[:MAX_ATTACHMENT_CHARS]

    return {"name": name, "readable": True, "text": text, "truncated": truncated, "kind": None}


def _attachment_prompt_block(info: dict) -> str:
    """Renders an _extract_attachment() record as the labeled block folded into the
    query text -- ALWAYS returns something (never blank) so the model knows an
    attachment exists even when its content couldn't be read; silently saying nothing
    was indistinguishable from no file being attached at all, which is what produced
    replies like "I don't see a file attached"."""
    name = info["name"]
    if info["readable"]:
        note = "\n\n[...truncated]" if info["truncated"] else ""
        body = f"{info['text']}{note}"
    elif info["kind"]:
        body = (
            f"[This is a {info['kind']} file. Its content can't be read yet -- text "
            f"extraction for this format isn't supported. Tell the user their file was "
            f"received but you can't see inside it.]"
        )
    else:
        body = (
            f"[This file's content can't be read (not a recognized text or supported "
            f"document format). Tell the user their file was received but you can't see "
            f"inside it.]"
        )
    return f"--- Attached file: {name} ---\n{body}\n--- End of {name} ---"


async def _apply_attachment(query: str, file: Optional[UploadFile]) -> tuple[str, Optional[dict]]:
    """Folds an uploaded file's content (if any -- as real text, or a clear "unreadable"
    note when it isn't) ahead of the query, and returns the file's _extract_attachment()
    record alongside it for the caller to persist via record_message(attachments=...).
    Returns (query, None) unchanged when there's no file, so callers can pass the second
    value straight through without an extra None-check."""
    if not file:
        return query, None
    info = await _extract_attachment(file)
    return f"{_attachment_prompt_block(info)}\n\n{query}", info


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _format_plan_message(plan: dict) -> str:
    """Renders a plan as chat-friendly markdown, for the persisted message history."""
    if not plan:
        return "I couldn't come up with a plan for that -- could you rephrase the ticket?"

    lines = ["Here's my proposed plan -- let me know if you'd like changes, or approve it to start building.", ""]
    assumptions = plan.get("assumptions") or []
    if assumptions:
        lines.append("**Assumptions:**")
        lines.extend(f"- {a}" for a in assumptions)
        lines.append("")

    tasks = plan.get("tasks") or []
    if tasks:
        lines.append("**Tasks:**")
        lines.extend(f"- **{t.get('id')}**: {t.get('description')}" for t in tasks)

    return "\n".join(lines)


def _plan_message_payload(plan: dict | None, ticket: str):
    """
    What gets persisted as an assistant message's `content` for a Planner turn.

    When a plan was produced, this is a structured object (not just the flattened
    markdown _format_plan_message() renders) so history replay can rebuild the same rich
    plan card the user saw live -- task ID badges, separate Assumptions/Tasks sections --
    instead of a wall of plain text (see static/js/app.js's selectConversation() +
    renderPlanMessage()). `text` is kept alongside as a plain-text fallback for anything
    that expects a string (e.g. conversation_history fed into Summary/Intent's prompts).

    Falls back to the flattened text alone when there's no plan (Planner failed) --
    nothing structured to replay in that case, same as a chat_reply.
    """
    text = _format_plan_message(plan)
    if not plan:
        return text
    return {"type": "plan", "text": text, "plan": plan, "ticket": ticket}


def _plan_turn_message(result: dict, ticket: str):
    """
    What actually gets persisted as the assistant message for a Planner-phase turn --
    shared by /run, /run/stream, and /replan so all three treat a failed Planner call
    the same way.

    Priority: chat_reply (CHAT/SNIPPET, Planner never ran) > error (Planner/Intent call
    failed) > the plan card (or its "couldn't come up with a plan" fallback).

    Without the `error` branch, a failed call's friendly message (see
    agents/common/errors.py) was shown live via the SSE "error" field but NEVER
    persisted -- record_message() always got _plan_message_payload(None, ...)'s
    generic "I couldn't come up with a plan for that -- could you rephrase the ticket?"
    instead, since that fallback doesn't know an error even happened. history replay
    then showed a DIFFERENT, less informative message than what was shown live,
    silently losing the actual reason the moment the SSE connection closed.
    """
    chat_reply = result.get("chat_reply")
    if chat_reply is not None:
        return chat_reply
    error = result.get("error")
    if error:
        return error
    return _plan_message_payload(result.get("plan"), ticket)


@router.post('/run', dependencies=[_require_full])
async def run_agent(
    user_id: str = Form(...),
    query: str = Form(...),
    file: Optional[UploadFile] = File(None),
    conversation_id: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Phase 1 of the ticket pipeline: runs the Planner only and returns the proposed plan
    for approval. No code is written yet -- see /build for phase 2, which requires the
    plan this endpoint returns (optionally edited by the user first).
    """
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    effective_query, attachment = await _apply_attachment(query, file)

    result, summary = await start_plan(user_id, effective_query, conversation_id)

    # chat_reply is set when the intent gate in start_plan() classified this message
    # as chit-chat/a snippet rather than a ticket -- the Planner never ran, so there's
    # no plan to render, just this direct reply.
    chat_reply = result.get("chat_reply")
    assistant_message = _plan_turn_message(result, result.get("ticket") or query)

    record_message(
        user_id, conversation_id, "user", query,
        attachments=[attachment] if attachment else None,
    )
    record_message(user_id, conversation_id, "assistant", assistant_message)
    end_conversation(user_id, conversation_id, db, summary)

    return {
        "conversation_id": conversation_id,
        "plan": result.get("plan"),
        "reply": chat_reply,
        "error": result.get("error"),
    }


@router.post('/run/stream', dependencies=[_require_full])
async def run_agent_stream(
    user_id: str = Form(...),
    query: str = Form(...),
    file: Optional[UploadFile] = File(None),
    conversation_id: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Streaming counterpart to /run: same intent-check -> Planner (or direct chit-chat
    reply) work, but pushes real "phase" events to the client as they happen -- e.g.
    "Reading your message…" -> "Planning the work…" -> "Wrapping up…" -- instead of the
    client seeing one static "Thinking…" for the whole request. Ends with a "result"
    event carrying the same shape /run returns, or an "error" event.

    Unlike /build/stream, start_plan() is plain async work (no CrewAI event-bus/thread
    crossing involved), so phase events are pushed straight into an asyncio.Queue from
    the on_phase callback -- no worker thread needed.
    """
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    effective_query, attachment = await _apply_attachment(query, file)

    async def event_stream():
        phase_queue: "asyncio.Queue[dict]" = asyncio.Queue()

        async def on_phase(message: str):
            await phase_queue.put({"type": "phase", "message": message})

        async def run_and_finish():
            try:
                result, summary = await start_plan(user_id, effective_query, conversation_id, on_phase=on_phase)
                await phase_queue.put({"type": "done", "result": result, "summary": summary})
            except Exception as exc:  # noqa: BLE001 -- reported to the client as a stream event
                logger.exception("Error in /run/stream")
                await phase_queue.put({"type": "error", "message": friendly_error_message(exc)})

        task = asyncio.create_task(run_and_finish())

        try:
            while True:
                event = await phase_queue.get()

                if event["type"] == "done":
                    result = event["result"]
                    summary = event["summary"]
                    chat_reply = result.get("chat_reply")
                    assistant_message = _plan_turn_message(result, result.get("ticket") or query)

                    record_message(
                        user_id, conversation_id, "user", query,
                        attachments=[attachment] if attachment else None,
                    )
                    record_message(user_id, conversation_id, "assistant", assistant_message)
                    end_conversation(user_id, conversation_id, db, summary)

                    yield _sse({
                        "type": "result",
                        "conversation_id": conversation_id,
                        "plan": result.get("plan"),
                        "reply": chat_reply,
                        "error": result.get("error"),
                    })
                    return

                if event["type"] == "error":
                    yield _sse(event)
                    return

                yield _sse(event)
        finally:
            task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post('/replan', dependencies=[_require_full])
async def replan(
    user_id: str = Form(...),
    conversation_id: str = Form(...),
    feedback: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    "Request changes" on a plan the user already saw: re-runs the Planner with the
    user's feedback against the pending plan for this conversation.
    """
    result, summary = await revise_plan(user_id, conversation_id, feedback)

    record_message(user_id, conversation_id, "user", feedback)
    record_message(
        user_id,
        conversation_id,
        "assistant",
        _plan_turn_message(result, result.get("ticket") or feedback),
    )
    end_conversation(user_id, conversation_id, db, summary)

    return {
        "conversation_id": conversation_id,
        "plan": result.get("plan"),
        "error": result.get("error"),
    }


@router.post('/build', dependencies=[_require_full])
async def build(
    user_id: str = Form(...),
    conversation_id: str = Form(...),
    plan: str = Form(...),
    ticket: Optional[str] = Form(None),
    max_retries: int = Form(3),
    db: Session = Depends(get_db)
):
    """
    Phase 2 of the ticket pipeline: runs Coder -> Reviewer against the approved plan
    (`plan` is the JSON from /run or /replan, possibly hand-edited by the user in the UI).
    """
    try:
        plan_obj = json.loads(plan)
    except json.JSONDecodeError:
        return {"error": "plan is not valid JSON"}

    result, summary = await build_from_plan(
        user_id, conversation_id, plan_obj, ticket=ticket, max_retries=max_retries
    )

    response_text = result.get("code_summary") or result.get("error") or "No result"
    record_message(user_id, conversation_id, "assistant", response_text)
    end_conversation(user_id, conversation_id, db, summary)

    return {
        "result": response_text,
        "approved": result.get("approved"),
        "retries_used": result.get("retries_used"),
        "error": result.get("error"),
    }


@router.post('/build/stream', dependencies=[_require_full])
async def build_stream(
    user_id: str = Form(...),
    conversation_id: str = Form(...),
    plan: str = Form(...),
    ticket: Optional[str] = Form(None),
    max_retries: int = Form(3),
    db: Session = Depends(get_db)
):
    """
    Streaming counterpart to /build: same phase 2 (Coder -> Reviewer), but pushed to the
    client as Server-Sent Events as they happen instead of one response at the end --
    "phase" events (a short status label), "file" events (a file the Coder just wrote,
    with its full content, for progressive rendering), and a final "result" or "error"
    event. The pipeline itself runs on a worker thread; see research.build_from_plan_worker
    and agents/ticket_pipeline/events.py for how progress crosses that thread boundary.
    """
    try:
        plan_obj = json.loads(plan)
    except json.JSONDecodeError:
        async def bad_plan_stream():
            yield _sse({"type": "error", "message": "plan is not valid JSON"})
        return StreamingResponse(bad_plan_stream(), media_type="text/event-stream")

    async def event_stream():
        progress_queue: "queue.Queue[dict]" = queue.Queue()
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            None,
            build_from_plan_worker,
            user_id,
            conversation_id,
            plan_obj,
            ticket,
            max_retries,
            progress_queue,
        )

        # Paths this build actually wrote to, in first-written order -- built up from the
        # same "file" events forwarded to the client below, so what gets persisted always
        # matches what the live file chips showed. Deduped so a retry rewriting the same
        # file doesn't persist it twice; content itself is never kept here, only the path
        # -- GET /workspace_file reads the current content back off disk on demand.
        written_paths: list[str] = []
        seen_paths: set[str] = set()

        while True:
            event = await loop.run_in_executor(None, progress_queue.get)

            if event["type"] == "file" and event.get("path") not in seen_paths:
                seen_paths.add(event["path"])
                written_paths.append(event["path"])

            if event["type"] == "done":
                result = event["result"]
                summary = event["summary"]
                response_text = result.get("code_summary") or result.get("error") or "No result"
                record_message(
                    user_id, conversation_id, "assistant", response_text,
                    files=written_paths or None,
                )
                end_conversation(user_id, conversation_id, db, summary)
                yield _sse({
                    "type": "result",
                    "result": response_text,
                    "approved": result.get("approved"),
                    "retries_used": result.get("retries_used"),
                    "error": result.get("error"),
                })
                return

            if event["type"] == "error":
                yield _sse(event)
                return

            yield _sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post('/run_ticket', dependencies=[_require_full])
async def run_ticket(
    user_id: str,
    ticket: str,
    conversation_id: Optional[str] = None,
    max_retries: int = 3,
    db: Session = Depends(get_db)
):
    """
    Runs one turn of the Planner -> Coder -> Reviewer pipeline against `ticket`.
    Reuses the same conversation_id/history plumbing as /run so a follow-up ticket
    ("agrégale también X") on the same conversation is treated as an iteration.
    """
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    result = await run_ticket_pipeline(ticket, conversation_id, max_retries=max_retries)

    summary_text = result.get("code_summary") or result.get("error") or "No result"
    record_message(user_id, conversation_id, "user", ticket)
    record_message(user_id, conversation_id, "assistant", summary_text)
    end_conversation(user_id, conversation_id, db, summary_text[:120])

    return result

@router.post('/end_conversation', dependencies=[_require_full])
def end_chat(user_id: str, conversation_id: str, db: Session = Depends(get_db)):
    return end_conversation(user_id, conversation_id, db)

@router.get('/get_history')
def history(user_id: str, db: Session = Depends(get_db)):
    return load_user_history(db, user_id)

@router.delete('/delete_conversation', dependencies=[_require_full])
def delete_conversation_endpoint(user_id: str, conversation_id: str, db: Session = Depends(get_db)):
    return delete_conversation(user_id, db, conversation_id)

@router.get('/api/readme')
def get_readme():
    """
    Raw README.md content for the frontend's "About" tab (static/js/app.js's
    loadMarkdownDoc()), which renders it client-side via marked.js -- this endpoint
    deliberately returns markdown, not HTML, so there's no server-side rendering
    dependency. Reads from disk on every call rather than caching in memory: README.md
    changes rarely and this is a low-traffic, dev-facing endpoint, so the simplicity of
    always reading the current file outweighs any benefit from caching it.
    """
    try:
        content = README_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"error": f"README.md not found at {README_PATH}"},
        )
    return {"content": content}


@router.get('/api/retro')
def get_retro():
    """
    Raw WHAT_I_WOULD_DO_DIFFERENTLY.md content for the frontend's "What I'd Do
    Differently" tab. Same pattern as get_readme() above -- a separate file, not a
    section carved out of README.md, so it gets its own tiny endpoint rather than the
    frontend guessing at a heading to extract.
    """
    try:
        content = RETRO_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"error": f"WHAT_I_WOULD_DO_DIFFERENTLY.md not found at {RETRO_PATH}"},
        )
    return {"content": content}


@router.get('/workspace_file')
def get_workspace_file(conversation_id: str, path: str):
    """
    Serves one file's CURRENT content from a conversation's on-disk workspace
    (workspaces/<conversation_id>/, see agents/ticket_pipeline/flow.py's
    WORKSPACES_ROOT). The persisted message row for a build turn only carries the
    file's path (see record_message(..., files=...) in /build/stream above), not its
    content, so this is what the frontend's file pane fetches on demand the first time a
    replayed build-file chip is clicked (see static/js/app.js's openWorkspaceFile()) --
    mirrors how a LIVE build's chips already have their content in hand from the "file"
    SSE event, just fetched lazily instead of pushed eagerly.

    Reuses the same containment guard the Coder/Reviewer's own file tools are built on
    (agents/ticket_pipeline/tools.py's resolve_in_workspace()), so a path like
    '../../backend/db.py' is rejected here exactly as it would be inside a crew run.
    """
    root = WORKSPACES_ROOT / conversation_id
    try:
        target = resolve_in_workspace(root, path)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    if not target.is_file():
        return JSONResponse(
            status_code=404,
            content={"error": f"'{path}' was not found in this conversation's workspace."},
        )

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return JSONResponse(
            status_code=415,
            content={"error": "This file isn't readable as text."},
        )

    return {"path": path, "content": content}


@router.get('/trace')
def trace(user_id: str, conversation_id: str):
    """
    Every intermediate agent decision recorded for this conversation, grouped by the chat
    turn each step belongs to -- what intent a message was classified as (and why), what
    approach the Planner chose, what the Coder implemented, and whether the Reviewer
    approved it (and why not, if it didn't). Each step is short -- {agent, decision,
    reasoning, timestamp} -- never the full chat/build response text; that's already in
    the transcript (see agents/ticket_pipeline/flow.py's TicketState.trace and
    backend/services/chat.py's record_trace()/get_trace()). Deliberately not surfaced in
    the chat transcript itself; this is the accessible-but-separate view of it -- the UI's
    "View agent trace" panel reads from here. Shape:

        {"conversation_id": "...", "turns": [
            {"turn_id": "...", "steps": [{"agent", "decision", "reasoning", "timestamp"}, ...]},
            ...
        ]}
    """
    return {"conversation_id": conversation_id, "turns": get_trace(user_id, conversation_id)}
