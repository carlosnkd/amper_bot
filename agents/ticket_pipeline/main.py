import logging

from agents.ticket_pipeline.flow import TicketFlow
from backend.cache.ticket_cache import append_ticket_turn, get_ticket_history

logger = logging.getLogger(__name__)


async def run_ticket_pipeline(
    ticket: str, conversation_id: str, max_retries: int = 3
) -> dict:
    """
    Runs one turn of the Planner -> Coder -> Reviewer pipeline for `ticket`.

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
    }
