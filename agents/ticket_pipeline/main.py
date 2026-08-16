import logging

from agents.ticket_pipeline.flow import TicketBuildFlow, TicketFlow, TicketPlanFlow
from backend.cache.ticket_cache import append_ticket_turn, get_ticket_history

logger = logging.getLogger(__name__)


async def plan_ticket(
    ticket: str, conversation_id: str, plan_feedback: str | None = None, previous_plan: dict | None = None,
    test_mode: list | None = None
) -> dict:
    """
    Runs the Planner only (phase 1 of the pipeline) and returns the proposed plan without
    writing any code, so it can be shown to the user for approval first.

    `plan_feedback` + `previous_plan` are set when this is a revision turn ("request
    changes" on a plan the user already saw) rather than a brand-new ticket.
    """
    if test_mode is not None:
        prior_turns = test_mode
    else:
        prior_turns = get_ticket_history(conversation_id)

    flow = TicketPlanFlow()
    final_state = await flow.kickoff_async(
        inputs={
            "conversation_id": conversation_id,
            "ticket": ticket,
            "history": prior_turns,
            "plan_feedback": plan_feedback,
            "plan": previous_plan,
        }
    )

    return {
        "conversation_id": conversation_id,
        "ticket": ticket,
        "plan": final_state.plan,
        "error": final_state.error,
        "trace": final_state.trace,
    }


async def build_ticket(
    ticket: str,
    conversation_id: str,
    plan: dict,
    max_retries: int = 3,
) -> dict:
    """
    Runs Coder -> Reviewer (phase 2) against `plan`, which the user has already approved
    (and may have hand-edited). `plan` is used as-is -- the Planner does not run again.
    """
    flow = TicketBuildFlow()
    final_state = await flow.kickoff_async(
        inputs={
            "conversation_id": conversation_id,
            "ticket": ticket,
            "max_retries": max_retries,
            "plan": plan,
        }
    )

    if final_state.history:
        append_ticket_turn(conversation_id, final_state.history[-1])

    return {
        "conversation_id": conversation_id,
        "plan": final_state.plan,
        "code_summary": final_state.code_summary,
        "approved": final_state.approved,
        "retries_used": final_state.retry_count,
        "error": final_state.error,
        "trace": final_state.trace,
    }


async def run_ticket_pipeline(
    ticket: str, conversation_id: str, max_retries: int = 3
) -> dict:
    """
    Runs one turn of the Planner -> Coder -> Reviewer pipeline for `ticket` with no
    approval checkpoint in between -- kept for callers (e.g. /run_ticket) that want the
    old one-shot behavior. The interactive chat flow uses plan_ticket()/build_ticket()
    instead so the plan can be approved before any code is written.

    Prior turns for `conversation_id` are loaded and handed to the Planner as context, so a
    follow-up message like "agrégale también X" is understood as an iteration on the same
    ticket rather than an unrelated new one.

    Returns a dict with the resulting plan, a summary of the code written, whether the
    Reviewer approved it, how many retries it took, and an `error` field (None on success).
    """
    prior_turns = get_ticket_history(conversation_id)

    flow = TicketFlow()
    final_state = await flow.kickoff_async(
        inputs={
            "conversation_id": conversation_id,
            "ticket": ticket,
            "max_retries": max_retries,
            "history": prior_turns,
        }
    )

    if final_state.history:
        append_ticket_turn(conversation_id, final_state.history[-1])

    return {
        "conversation_id": conversation_id,
        "plan": final_state.plan,
        "code_summary": final_state.code_summary,
        "approved": final_state.approved,
        "retries_used": final_state.retry_count,
        "error": final_state.error,
        "trace": final_state.trace,
    }
