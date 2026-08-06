"""
In-memory store for a plan that has been proposed to the user but not yet approved.

The ticket pipeline now runs in two turns: `/run` produces a plan (Planner only) and
parks it here; `/build` (after the user approves, possibly with edits) or `/replan`
(after the user asks for changes) picks it back up by conversation_id. Same
in-memory-dict pattern as backend/cache/ticket_cache.py and conversation_cache.py --
swap for a real table if a pending plan needs to survive a process restart.
"""

_pending_plans: dict[str, dict] = {}


def set_pending_plan(conversation_id: str, ticket: str, plan: dict, turn_id: str | None = None) -> None:
    # turn_id ties this plan back to the agent-trace turn that produced it (see
    # research.py's start_plan()/revise_plan()), so build_from_plan() can tag the
    # eventual Coder/Reviewer steps under the SAME turn instead of starting a new one --
    # optional only for callers that don't care about trace grouping.
    _pending_plans[conversation_id] = {"ticket": ticket, "plan": plan, "turn_id": turn_id}


def get_pending_plan(conversation_id: str) -> dict | None:
    return _pending_plans.get(conversation_id)


def clear_pending_plan(conversation_id: str) -> None:
    _pending_plans.pop(conversation_id, None)
