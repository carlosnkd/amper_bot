import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from crewai import Crew, Process
from crewai.flow.flow import Flow, start
from pydantic import BaseModel, Field

from agents.ticket_pipeline.agent import coder_agent, planner_agent, reviewer_agent
from agents.ticket_pipeline.events import publish_phase
from agents.ticket_pipeline.tasks import (
    build_code_task,
    build_plan_task,
    build_review_task,
)
from agents.ticket_pipeline.tools import set_active_workspace

logger = logging.getLogger(__name__)

WORKSPACES_ROOT = Path(__file__).resolve().parents[2] / "workspaces"


class TicketState(BaseModel):
    conversation_id: str = ""
    ticket: str | None = None
    max_retries: int = 3

    # Prior turns for this conversation, oldest first. Plain dicts (not a nested Pydantic
    # model) on purpose -- this is exactly the shape stored in/loaded from the cross-turn
    # cache, so no translation layer is needed at either end.
    history: list[dict] = Field(default_factory=list)

    # Set when this turn is a revision request ("no, do X instead") rather than a fresh
    # plan or an approval -- only read by TicketPlanFlow._plan().
    plan_feedback: str | None = None

    plan: dict | None = None
    code_summary: str | None = None
    review_feedback: str | None = None
    approved: bool = False
    retry_count: int = 0
    error: str | None = None

    # Ordered record of what each agent actually decided this turn and WHY -- one entry
    # per Planner/Coder/Reviewer crew run (see _TicketSteps._record()), each a short
    # {agent, decision, reasoning, timestamp} -- never the full plan/code/response text;
    # that's already what the chat bubble shows, duplicating it here would just be noise.
    # Not shown in the chat transcript; persisted separately (tagged with a turn_id by the
    # caller -- see backend/services/research.py) and surfaced on demand via GET /trace
    # (see backend/services/chat.py's record_trace()/get_trace() and routes.py).
    trace: list[dict] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(text: str | None, limit: int) -> str:
    """Caps a piece of agent output down to trace-entry length -- a short excerpt, not
    the full thing. Used wherever there's no separate LLM-authored reasoning to draw on."""
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _summarize_plan(plan: dict) -> str:
    """Heuristic 1-2 sentence summary of a Planner run for the trace panel, built from the
    plan's own assumptions/tasks rather than an extra LLM call -- the full plan is already
    shown in the plan card, this is only ever the trace's short "why"."""
    tasks = plan.get("tasks") or []
    assumptions = plan.get("assumptions") or []
    task_count = len(tasks)
    summary = f"Broke the ticket into {task_count} task{'s' if task_count != 1 else ''}."
    if assumptions:
        summary += f" Key assumption: {_truncate(assumptions[0], 140)}"
    return summary


def _parse_json_output(raw: str, step_name: str) -> dict:
    cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{step_name} did not return valid JSON: {raw!r}") from exc


class _TicketSteps:
    """
    Shared Planner/Coder/Reviewer crew-step methods, mixed into both TicketPlanFlow and
    TicketBuildFlow so each phase can be entered independently (crewai's Flow only
    supports a single @start() per class) without duplicating the crew-construction
    logic itself.
    """

    def _record(self, agent: str, decision: str, reasoning: str) -> None:
        """Appends one step to self.state.trace -- see TicketState.trace's docstring."""
        self.state.trace.append(
            {"agent": agent, "decision": decision, "reasoning": reasoning, "timestamp": _now()}
        )

    def _plan(self):
        history_text = (
            "\n".join(
                f"- Ticket: {turn.get('ticket')}\n"
                f"  Approved: {turn.get('approved')}\n"
                f"  Plan: {json.dumps(turn.get('plan'))}"
                for turn in self.state.history
            )
            or "(no previous turns)"
        )

        crew = Crew(
            agents=[planner_agent],
            tasks=[
                build_plan_task(
                    feedback=self.state.plan_feedback,
                    previous_plan=self.state.plan,
                )
            ],
            process=Process.sequential,
            verbose=True,
        )
        result = crew.kickoff(
            inputs={"ticket": self.state.ticket, "history": history_text}
        )
        self.state.plan = _parse_json_output(result.raw, "Planner")
        self._record(
            "PLANNER",
            "revised_plan" if self.state.plan_feedback else "created_plan",
            _summarize_plan(self.state.plan),
        )

    def _code(self):
        crew = Crew(
            agents=[coder_agent],
            tasks=[build_code_task(feedback=self.state.review_feedback)],
            process=Process.sequential,
            verbose=True,
        )
        result = crew.kickoff(inputs={"plan": json.dumps(self.state.plan)})
        self.state.code_summary = result.raw
        # code_summary is the Coder's own plain-text account of what it changed -- reused
        # here as the trace's reasoning, just length-capped rather than duplicated in full
        # (the complete summary is already what the chat bubble shows once the build
        # finishes). Retry round number isn't recorded explicitly -- the trace panel
        # infers it from a step's position among the turn's CODER/REVIEWER pairs.
        self._record("CODER", "implemented", _truncate(self.state.code_summary, 220))

    def _review(self):
        crew = Crew(
            agents=[reviewer_agent],
            tasks=[build_review_task()],
            process=Process.sequential,
            verbose=True,
        )
        result = crew.kickoff(inputs={"plan": json.dumps(self.state.plan)})
        verdict = _parse_json_output(result.raw, "Reviewer")
        self.state.approved = bool(verdict.get("approved"))
        self.state.review_feedback = verdict.get("feedback") or None
        reasoning = (
            _truncate(self.state.review_feedback, 220)
            if self.state.review_feedback
            else "All planned tasks implemented and verified."
        )
        self._record("REVIEWER", "approved" if self.state.approved else "rejected", reasoning)


class TicketPlanFlow(_TicketSteps, Flow[TicketState]):
    """
    Phase 1: runs the Planner only and stops there.

    Used both for a fresh ticket and for a revision ("request changes") turn -- in the
    latter case `self.state.plan_feedback` (and, for context, the previous `self.state.plan`)
    are set before kickoff, and `_plan()` folds them into the Planner's prompt.

    The result is shown to the user for approval before any code gets written, instead of
    running the full (and much slower) Planner -> Coder -> Reviewer loop unattended.
    """

    @start()
    def run(self):
        workspace = WORKSPACES_ROOT / (self.state.conversation_id or "default")
        set_active_workspace(workspace)
        try:
            self._plan()
        except Exception as exc:
            logger.exception("Error planning ticket")
            self.state.error = str(exc)
        return self.state


class TicketBuildFlow(_TicketSteps, Flow[TicketState]):
    """
    Phase 2: runs Coder -> Reviewer against an already-approved plan, retrying the Coder
    (with the Reviewer's feedback) up to `max_retries` times whenever the Reviewer rejects
    the work. `self.state.plan` must already be set on kickoff -- either the plan
    TicketPlanFlow produced, or that same plan after the user edited it by hand.
    """

    @start()
    def run(self):
        workspace = WORKSPACES_ROOT / (self.state.conversation_id or "default")
        set_active_workspace(workspace)

        try:
            publish_phase("Writing the code…")
            while True:
                self._code()
                publish_phase("Reviewing the changes…")
                self._review()
                if self.state.approved:
                    logger.info(
                        "Ticket approved after %d retr%s (conversation_id=%s)",
                        self.state.retry_count,
                        "y" if self.state.retry_count == 1 else "ies",
                        self.state.conversation_id,
                    )
                    break
                if self.state.retry_count >= self.state.max_retries:
                    tries = self.state.retry_count + 1
                    logger.warning(
                        "Ticket pipeline exhausted %d retries without approval "
                        "(conversation_id=%s). Returning the last attempt.",
                        self.state.max_retries,
                        self.state.conversation_id,
                    )
                    self._record(
                        "SYSTEM",
                        "max_retries_reached",
                        f"Returning last Coder attempt, unresolved Reviewer disagreement "
                        f"after {tries} tries.",
                    )
                    break
                self.state.retry_count += 1
                publish_phase(
                    f"Retry {self.state.retry_count}/{self.state.max_retries}: "
                    "revising based on reviewer feedback…"
                )
        except Exception as exc:
            logger.exception("Error building ticket")
            self.state.error = str(exc)

        self.state.history.append(
            {
                "ticket": self.state.ticket,
                "plan": self.state.plan,
                "code_summary": self.state.code_summary,
                "approved": self.state.approved,
                "retries_used": self.state.retry_count,
            }
        )
        return self.state


class TicketFlow(_TicketSteps, Flow[TicketState]):
    """
    Full Planner -> Coder -> Reviewer pipeline in one shot, with no approval checkpoint in
    between. Kept for callers that want the old one-turn behavior (e.g. /run_ticket) --
    the interactive chat flow now goes through TicketPlanFlow then TicketBuildFlow instead,
    so the user can review the plan before any code gets written.
    """

    @start()
    def run(self):
        workspace = WORKSPACES_ROOT / (self.state.conversation_id or "default")
        set_active_workspace(workspace)

        try:
            self._plan()
            while True:
                self._code()
                self._review()
                if self.state.approved:
                    logger.info(
                        "Ticket approved after %d retr%s (conversation_id=%s)",
                        self.state.retry_count,
                        "y" if self.state.retry_count == 1 else "ies",
                        self.state.conversation_id,
                    )
                    break
                if self.state.retry_count >= self.state.max_retries:
                    tries = self.state.retry_count + 1
                    logger.warning(
                        "Ticket pipeline exhausted %d retries without approval "
                        "(conversation_id=%s). Returning the last attempt.",
                        self.state.max_retries,
                        self.state.conversation_id,
                    )
                    self._record(
                        "SYSTEM",
                        "max_retries_reached",
                        f"Returning last Coder attempt, unresolved Reviewer disagreement "
                        f"after {tries} tries.",
                    )
                    break
                self.state.retry_count += 1
        except Exception as exc:
            logger.exception("Error running ticket pipeline")
            self.state.error = str(exc)

        self.state.history.append(
            {
                "ticket": self.state.ticket,
                "plan": self.state.plan,
                "code_summary": self.state.code_summary,
                "approved": self.state.approved,
                "retries_used": self.state.retry_count,
            }
        )
        return self.state
