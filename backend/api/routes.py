import asyncio
import json
import queue
import uuid
from backend.main import get_db
from fastapi import APIRouter, UploadFile, File, Form, Depends
from fastapi.responses import StreamingResponse
from typing import Optional
from backend.services.research import build_from_plan, build_from_plan_worker, revise_plan, start_plan
from sqlalchemy.orm import Session
from backend.services.chat import (
    record_message,
    end_conversation,
    load_user_history,
    delete_conversation
)
from agents.ticket_pipeline.main import run_ticket_pipeline

router = APIRouter()


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


@router.post('/run')
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
    if file:
        pass

    result, summary = await start_plan(user_id, query, conversation_id)

    # chat_reply is set when the intent gate in start_plan() classified this message
    # as chit-chat rather than a ticket -- the Planner never ran, so there's no plan
    # to render, just this direct reply.
    chat_reply = result.get("chat_reply")
    assistant_message = chat_reply if chat_reply is not None else _format_plan_message(result.get("plan"))

    record_message(user_id, conversation_id, "user", query)
    record_message(user_id, conversation_id, "assistant", assistant_message)
    end_conversation(user_id, conversation_id, db, summary)

    return {
        "conversation_id": conversation_id,
        "plan": result.get("plan"),
        "reply": chat_reply,
        "error": result.get("error"),
    }


@router.post('/run/stream')
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
    if file:
        pass

    async def event_stream():
        phase_queue: "asyncio.Queue[dict]" = asyncio.Queue()

        async def on_phase(message: str):
            await phase_queue.put({"type": "phase", "message": message})

        async def run_and_finish():
            try:
                result, summary = await start_plan(user_id, query, conversation_id, on_phase=on_phase)
                await phase_queue.put({"type": "done", "result": result, "summary": summary})
            except Exception as exc:  # noqa: BLE001 -- reported to the client as a stream event
                await phase_queue.put({"type": "error", "message": str(exc)})

        task = asyncio.create_task(run_and_finish())

        try:
            while True:
                event = await phase_queue.get()

                if event["type"] == "done":
                    result = event["result"]
                    summary = event["summary"]
                    chat_reply = result.get("chat_reply")
                    assistant_message = (
                        chat_reply if chat_reply is not None else _format_plan_message(result.get("plan"))
                    )

                    record_message(user_id, conversation_id, "user", query)
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


@router.post('/replan')
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
    record_message(user_id, conversation_id, "assistant", _format_plan_message(result.get("plan")))
    end_conversation(user_id, conversation_id, db, summary)

    return {
        "conversation_id": conversation_id,
        "plan": result.get("plan"),
        "error": result.get("error"),
    }


@router.post('/build')
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


@router.post('/build/stream')
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

        while True:
            event = await loop.run_in_executor(None, progress_queue.get)

            if event["type"] == "done":
                result = event["result"]
                summary = event["summary"]
                response_text = result.get("code_summary") or result.get("error") or "No result"
                record_message(user_id, conversation_id, "assistant", response_text)
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


@router.post('/run_ticket')
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

@router.post('/end_conversation')
def end_chat(user_id: str, conversation_id: str, db: Session = Depends(get_db)):
    return end_conversation(user_id, conversation_id, db)

@router.get('/get_history')
def history(user_id: str, db: Session = Depends(get_db)):
    return load_user_history(db, user_id)

@router.delete('/delete_conversation')
def delete_conversation_endpoint(user_id: str, conversation_id: str, db: Session = Depends(get_db)):
    return delete_conversation(user_id, db, conversation_id)
