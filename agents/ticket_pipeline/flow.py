import json
import logging
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

    def _code(self):
        crew = Crew(
            agents=[coder_agent],
            tasks=[build_code_task(feedback=self.state.review_feedback)],
            process=Process.sequential,
            verbose=True,
        )
        result = crew.kickoff(inputs={"plan": json.dumps(self.state.plan)})
        self.state.code_summary = result.raw

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
                    logger.warning(
                        "Ticket pipeline exhausted %d retries without approval "
                        "(conversation_id=%s). Returning the last attempt.",
                        self.state.max_retries,
                        self.state.conversation_id,
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
                    logger.warning(
                        "Ticket pipeline exhausted %d retries without approval "
                        "(conversation_id=%s). Returning the last attempt.",
                        self.state.max_retries,
                        self.state.conversation_id,
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
