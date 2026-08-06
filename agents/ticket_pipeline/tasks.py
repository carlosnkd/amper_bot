"""
Task factories for the ticket pipeline.

Unlike agents/research/tasks.py (module-level Task singletons, run once per request),
these are functions that build a *new* Task each call. The Coder/Reviewer step can run
several times per ticket (once per retry) with different feedback baked into the
description each time, so the Task objects can't be reused as static singletons here.
"""

import json

from crewai import Task

from agents.ticket_pipeline.agent import coder_agent, planner_agent, reviewer_agent


def build_plan_task(feedback: str | None = None, previous_plan: dict | None = None) -> Task:
    revision_block = (
        f"""
            The user already saw this proposed plan and asked for changes instead of
            approving it. Revise it to address their feedback exactly -- keep whatever
            parts of the previous plan still apply, don't restart from scratch:

            Previous plan (JSON): {json.dumps(previous_plan) if previous_plan else "(none)"}

            User's requested changes: {feedback}
        """
        if feedback
        else ""
    )

    return Task(
        name="Plan Ticket",
        description=f"""
            Feature ticket for this turn: {{ticket}}

            Conversation history (previous tickets and whether their plan was ultimately
            approved), oldest first. Empty if this is the first turn:
            {{history}}
            {revision_block}
            Break the ticket down into a concrete, ordered list of technical tasks that a
            Coder agent can implement directly, with no further clarification needed.

            If this ticket is a follow-up on previous work (e.g. "agrégale también X"),
            extend or amend the most recent approved plan instead of starting from scratch --
            keep the parts of it that still apply.

            If the ticket is ambiguous, do not stop and ask -- pick the most reasonable
            interpretation and record it under "assumptions". Only record an assumption when
            it's a genuine fork in the road -- a choice that would meaningfully change the
            implementation if you guessed wrong (e.g. "storage backend" or "auth model" for a
            rate limiter). Do not record assumptions for defaults nobody would question (e.g.
            "the app is written in the same language as the rest of the codebase"). Aim for
            3-5; if you can't justify why a guess deserves to be there, leave it out.

            Size each task the way a senior engineer would size a unit of work to hand off --
            a coherent, reviewable chunk (e.g. "add the rate-limit middleware and wire it into
            the endpoint," not three separate tasks for "add config," "read config," and "wire
            it in"). Aim for 5-8 tasks for a typical ticket. A larger ticket can genuinely need
            more -- don't cut real scope to hit a number -- but never split one coherent change
            into multiple tasks just to look thorough.
        """,
        expected_output="""
            Valid JSON only, no markdown fences, no extra text, in exactly this shape:
            {
              "assumptions": ["<a genuine fork in the road, not a restated default>", "..."],
              "tasks": [
                {"id": "T1", "description": "<one coherent, reviewable unit of work>"},
                {"id": "T2", "description": "..."}
              ]
            }
        """,
        agent=planner_agent,
        output_file="plan.json",
    )


def build_code_task(feedback: str | None = None) -> Task:
    feedback_block = (
        f"The previous attempt at this plan was REJECTED by the Reviewer with this "
        f"feedback. Fix exactly what it flags before doing anything else:\n{feedback}"
        if feedback
        else "This is the first attempt at implementing this plan."
    )

    return Task(
        name="Implement Plan",
        description=f"""
            Plan to implement (JSON): {{plan}}

            {feedback_block}

            Use your file tools to write every file the plan requires directly to the
            workspace. Do not just describe what the code would look like -- create it.
            Check the existing workspace contents first (list_files / read_file) before
            overwriting anything from a previous attempt that's still correct.
        """,
        expected_output="""
            A short plain-text summary of the files you created or modified, one line per
            file, plus a one-line note per file explaining what it does.
        """,
        agent=coder_agent,
        output_file="code_summary.txt",
    )


def build_review_task() -> Task:
    return Task(
        name="Review Implementation",
        description="""
            Plan (JSON): {plan}

            Review every file currently in the workspace against every task in the plan.
            Run the syntax checker first -- if anything fails to compile, reject immediately.
            Otherwise, reject if any task from the plan is missing, incomplete, or clearly
            broken. Approve only if the workspace fully satisfies the plan.
        """,
        expected_output="""
            Valid JSON only, no markdown fences, no extra text, in exactly this shape:
            {
              "approved": <true|false>,
              "feedback": "<specific, actionable feedback for the Coder -- empty string if approved>"
            }
        """,
        agent=reviewer_agent,
        output_file="review.json",
    )
