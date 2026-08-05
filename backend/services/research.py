import asyncio
import queue

from agents.ticket_pipeline.main import build_ticket, plan_ticket, run_ticket_pipeline
from backend.services.bot.summary import Summary
from backend.cache.conversation_cache import get_conversation
from backend.cache.plan_cache import clear_pending_plan, get_pending_plan, set_pending_plan

summaryClass = Summary()


async def start_plan(user_id: str, query: str, conversation_id: str):
    """
    Phase 1: runs the Planner only (fast -- a single LLM call, not the whole
    Planner -> Coder -> Reviewer pipeline) and parks the result in plan_cache so /build
    or /replan can pick it back up once the user responds to it.
    """
    result = await plan_ticket(query, conversation_id)
    if result.get("plan"):
        set_pending_plan(conversation_id, query, result["plan"])

    conversation_history = get_conversation(user_id, conversation_id)
    summary = await summaryClass.generate_summary(conversation_history, query)

    return result, summary


async def revise_plan(user_id: str, conversation_id: str, feedback: str):
    """
    Phase 1b: re-runs the Planner with the user's requested changes folded in, against
    whatever plan is currently pending for this conversation.
    """
    pending = get_pending_plan(conversation_id)
    ticket = (pending or {}).get("ticket") or feedback
    previous_plan = (pending or {}).get("plan")

    result = await plan_ticket(
        ticket, conversation_id, plan_feedback=feedback, previous_plan=previous_plan
    )
    if result.get("plan"):
        set_pending_plan(conversation_id, ticket, result["plan"])

    conversation_history = get_conversation(user_id, conversation_id)
    summary = await summaryClass.generate_summary(conversation_history, feedback)

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
    clear_pending_plan(conversation_id)

    result = await build_ticket(resolved_ticket, conversation_id, plan, max_retries=max_retries)

    conversation_history = get_conversation(user_id, conversation_id)
    summary_source = result.get("code_summary") or resolved_ticket or "Implementation"
    summary = await summaryClass.generate_summary(conversation_history, summary_source)

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

    conversation_history = get_conversation(user_id, conversation_id)
    summary = await summaryClass.generate_summary(conversation_history, query)

    return result, summary
