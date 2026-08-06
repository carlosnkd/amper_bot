import asyncio
import logging
import queue
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable

from agents.ticket_pipeline.main import build_ticket, plan_ticket, run_ticket_pipeline
from backend.services.bot.intent import Intent
from backend.services.bot.summary import Summary
from backend.services.chat import get_conversation_history, record_trace
from backend.cache.plan_cache import clear_pending_plan, get_pending_plan, set_pending_plan

logger = logging.getLogger(__name__)

summaryClass = Summary()
intentClassifier = Intent()


async def _safe_summary(conversation_history, source_text: str) -> str:
    """
    Wraps Summary.generate_summary() so a hiccup in this one LLM call (rate limit,
    transient 400/500 from the API, etc.) never takes down the whole request -- the
    summary is only a cosmetic sidebar title, it shouldn't be able to discard an
    otherwise-successful plan or chat reply. Falls back to a truncated version of
    whatever text triggered this turn.
    """
    try:
        return await summaryClass.generate_summary(conversation_history, source_text)
    except Exception:
        logger.exception("Summary generation failed, falling back to a truncated title")
        fallback = (source_text or "Conversation").strip().replace("\n", " ")
        return fallback[:60] + ("…" if len(fallback) > 60 else "")


PhaseCallback = Callable[[str], Awaitable[None]] | None


async def _emit(on_phase: PhaseCallback, message: str) -> None:
    if on_phase:
        await on_phase(message)


async def start_plan(
    user_id: str, query: str, conversation_id: str, on_phase: PhaseCallback = None
):
    """
    Phase 1: runs the Planner only (fast -- a single LLM call, not the whole
    Planner -> Coder -> Reviewer pipeline) and parks the result in plan_cache so /build
    or /replan can pick it back up once the user responds to it.

    First gated by a cheap intent check so chit-chat ("what can you do") never reaches
    the Planner -- planner_agent is written to always produce a plan and never ask for
    clarification, so without this gate a casual message would come back as a fake
    implementation plan instead of a direct answer. See backend/services/bot/intent.py.

    `on_phase`, if given, is awaited with a short human-readable label before each major
    step -- /run/stream uses this to push real progress to the UI instead of a static
    "Thinking…" for the whole request. Optional and unused by plain /run.
    """
    await _emit(on_phase, "Reading your message…")
    conversation_history = get_conversation_history(user_id, conversation_id)
    classification = await intentClassifier.classify(conversation_history, query)
    intent = classification.get("intent")
    logger.info("Classified intent=%s for conversation_id=%s query=%r", intent, conversation_id, query)

    # One fresh turn_id per incoming message -- every agent-trace step this turn produces
    # (INTENT here, and PLANNER/CODER/REVIEWER/SYSTEM further down the TICKET path,
    # possibly across a later, separate /build request -- see build_from_plan()) shares
    # it, so GET /trace can regroup them into the single card group the panel renders for
    # this turn. See backend/models.py's AgentTraces docstring.
    turn_id = str(uuid.uuid4())

    # INTENT is recorded for every message regardless of which branch it takes below --
    # it's the one agent decision every single turn makes, so it's what keeps CHAT/SNIPPET
    # turns from showing up as a blank gap in the trace panel.
    intent_step = {
        "agent": "INTENT",
        "decision": intent,
        "reasoning": classification.get("reasoning") or "No reasoning provided.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # CHAT and SNIPPET are both answered directly, skipping the Planner entirely --
    # SNIPPET is a self-contained ask ("give me a FastAPI script") that doesn't touch
    # this product's own codebase, so there's nothing here to plan or review. See
    # backend/services/bot/intent.py for what distinguishes the two. The trace only ever
    # gets this marker step, never the actual reply text -- that's already in the chat
    # bubble, duplicating it into the trace would just be noise.
    if intent in ("CHAT", "SNIPPET"):
        router_step = {
            "agent": "ROUTER",
            "decision": "direct_response",
            "reasoning": "No Planner/Coder/Reviewer needed for this intent type.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        record_trace(user_id, conversation_id, turn_id, [intent_step, router_step])

        await _emit(on_phase, "Writing that up…" if intent == "SNIPPET" else "Got it — replying…")
        summary = await _safe_summary(conversation_history, query)
        result = {
            "conversation_id": conversation_id,
            "plan": None,
            "chat_reply": classification.get("reply") or "I'm not sure how to help with that yet.",
            "error": None,
        }
        return result, summary

    record_trace(user_id, conversation_id, turn_id, [intent_step])

    await _emit(on_phase, "Planning the work…")
    result = await plan_ticket(query, conversation_id)
    if result.get("plan"):
        set_pending_plan(conversation_id, query, result["plan"], turn_id)
    record_trace(user_id, conversation_id, turn_id, result.get("trace"))

    await _emit(on_phase, "Wrapping up…")
    summary = await _safe_summary(conversation_history, query)

    return result, summary


async def revise_plan(user_id: str, conversation_id: str, feedback: str):
    """
    Phase 1b: re-runs the Planner with the user's requested changes folded in, against
    whatever plan is currently pending for this conversation.

    This is its own chat turn (the user typed new feedback), so it gets its own fresh
    turn_id rather than reusing the original plan-proposal turn's -- and since it's the
    one that becomes "the pending plan" going forward, THIS turn_id is what
    build_from_plan() will pick up if the user approves it. No INTENT step here: the
    intent for a "request changes" reply is already known (it's a revision of a plan
    still on the table), so there's no fresh classification decision to record.
    """
    pending = get_pending_plan(conversation_id)
    ticket = (pending or {}).get("ticket") or feedback
    previous_plan = (pending or {}).get("plan")
    turn_id = str(uuid.uuid4())

    result = await plan_ticket(
        ticket, conversation_id, plan_feedback=feedback, previous_plan=previous_plan
    )
    if result.get("plan"):
        set_pending_plan(conversation_id, ticket, result["plan"], turn_id)
    record_trace(user_id, conversation_id, turn_id, result.get("trace"))

    conversation_history = get_conversation_history(user_id, conversation_id)
    summary = await _safe_summary(conversation_history, feedback)

    return result, summary


async def build_from_plan(
    user_id: str,
    conversation_id: str,
    plan: dict,
    ticket: str | None = None,
    max_retries: int = 3,
):
    """
    Phase 2: runs Coder -> Reviewer against `plan` (the pending plan, possibly hand-edited
    by the user in the UI first) and clears it from plan_cache once picked up.
    """
    pending = get_pending_plan(conversation_id)
    resolved_ticket = ticket or (pending or {}).get("ticket") or ""
    # Reuse the turn_id the plan was proposed (or last revised) under, so the Coder/
    # Reviewer/SYSTEM steps this produces land in the SAME trace-panel group as that
    # plan, even though this is a separate HTTP request. Only falls back to a fresh one if
    # plan_cache doesn't have it (e.g. a restart wiped the in-memory pending-plan store --
    # see plan_cache.py's own docstring on that limitation) -- worst case this build just
    # starts its own group instead of failing.
    turn_id = (pending or {}).get("turn_id") or str(uuid.uuid4())
    clear_pending_plan(conversation_id)

    result = await build_ticket(resolved_ticket, conversation_id, plan, max_retries=max_retries)
    record_trace(user_id, conversation_id, turn_id, result.get("trace"))

    conversation_history = get_conversation_history(user_id, conversation_id)
    summary_source = result.get("code_summary") or resolved_ticket or "Implementation"
    summary = await _safe_summary(conversation_history, summary_source)

    return result, summary


def build_from_plan_worker(
    user_id: str,
    conversation_id: str,
    plan: dict,
    ticket: str | None,
    max_retries: int,
    progress_queue: "queue.Queue[dict]",
) -> None:
    """
    Synchronous entry point for build_from_plan(), meant to run on a background thread
    (via loop.run_in_executor) so /build/stream can drain `progress_queue` for live
    CrewAI progress events while this runs. Sets the ContextVar events.py's handlers read
    from *before* kickoff, so tool/phase events emitted deep inside the pipeline land on
    the right request's queue -- see events.py's module docstring for why that works even
    though the event bus calls handlers from its own thread pool.

    Always puts a final {"type": "done", ...} or {"type": "error", ...} event on the
    queue before returning, so the SSE generator knows when to stop waiting.
    """
    from agents.ticket_pipeline.events import set_active_queue

    set_active_queue(progress_queue)
    try:
        result, summary = asyncio.run(
            build_from_plan(user_id, conversation_id, plan, ticket=ticket, max_retries=max_retries)
        )
        progress_queue.put({"type": "done", "result": result, "summary": summary})
    except Exception as exc:  # noqa: BLE001 -- reported to the client as a stream event
        progress_queue.put({"type": "error", "message": str(exc)})
    finally:
        set_active_queue(None)


async def run_query(user_id: str, query: str, conversation_id: str, max_retries: int = 3):
    """One-shot Planner -> Coder -> Reviewer with no approval checkpoint. Kept for /run_ticket."""
    result = await run_ticket_pipeline(query, conversation_id, max_retries=max_retries)

    conversation_history = get_conversation_history(user_id, conversation_id)
    summary = await _safe_summary(conversation_history, query)

    return result, summary
