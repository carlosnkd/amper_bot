import json
import logging

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Intent:
    """
    Front door for /run: classifies the user's latest message into one of three
    buckets before anything reaches the Planner:

    - TICKET  -- a concrete request to build/change/fix something in THIS
      product's own codebase. Goes to the Planner -> Coder -> Reviewer pipeline,
      which plans tasks and writes real files to the ticket workspace.
    - CHAT    -- small talk, greetings, or questions about the assistant itself.
    - SNIPPET -- a self-contained technical question or "write me a quick X"
      request that has nothing to do with modifying this product (e.g. "give me
      a simple FastAPI script", "how does Python's GIL work"). Doesn't belong in
      the ticket pipeline either -- there's nothing of ours to plan or review --
      but deserves a real, code-capable answer, not a chit-chat brush-off.

    CHAT and SNIPPET are handled identically downstream (see start_plan() in
    backend/services/research.py): both skip the Planner entirely and this
    class's own "reply" is shown to the user directly. The distinction exists so
    the prompt/token budget can be tuned for "a sentence or two" (CHAT) vs
    "a short block of working code" (SNIPPET) without one bleeding into the other.

    Without this gate, everything -- including "what can you do" -- reaches
    planner_agent (agents/ticket_pipeline/agent.py), whose task is explicitly
    written to always produce a plan and never ask for clarification, so a
    casual message comes back as a fake implementation plan instead of an
    answer. Runs on Haiku (like Summary) since it's a single cheap
    classification call, not full agentic work -- keeps chit-chat/snippets near
    instant and avoids paying for a Planner call that would get discarded.
    """

    classify_prompt = """
    You are the front door of a coding assistant that turns feature tickets into
    implementation plans. Before anything reaches the Planner, decide what the
    user's latest message is:

    - "TICKET": a concrete request to build, change, fix, or investigate something
      in THIS product's own codebase -- anything a Planner could turn into
      engineering tasks that get written to this product's workspace, even if
      it's phrased casually or is a follow-up on prior work.
    - "SNIPPET": a self-contained technical request that does NOT touch this
      product's codebase -- e.g. "write me a simple FastAPI hello-world script",
      "give me a regex for emails", "how do I reverse a linked list in Python".
      Nothing to plan or review here; just answer directly, with working code
      when code was asked for.
    - "CHAT": anything else -- greetings, small talk, questions about what the
      assistant can do or how it works, or requests unrelated to building or
      writing anything right now.

    Consider the full conversation history for context, not just the latest
    message in isolation.

    **Response Structure** (STRICT):
    - Return a JSON object only, with exactly three keys: "intent", "reasoning", and "reply".
    - "intent" is exactly one of "TICKET", "SNIPPET", "CHAT".
    - "reasoning" is REQUIRED for every intent: one short sentence (under ~160 characters)
      explaining what about the message drove this classification -- e.g. "Asks to add a
      new endpoint to this product's own backend" or "Small talk with no request to build
      or change anything." This is shown to developers in an agent-trace panel, not to the
      end user -- it must NEVER just restate "reply" or repeat the user's message verbatim.
    - "reply" is REQUIRED when intent is "SNIPPET" or "CHAT": the actual answer,
      written as the assistant. For SNIPPET, include real, working code (in a
      markdown code block) plus at most a sentence or two of context -- don't
      pad it with unnecessary caveats. For CHAT, a short, direct, friendly
      answer; mention you can plan and build features or fixes when relevant.
    - "reply" MUST be an empty string when intent is "TICKET" -- the Planner
      handles that turn instead, not you.
    - No text before or after the JSON object.
    """

    _schema = {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["TICKET", "SNIPPET", "CHAT"]},
            "reasoning": {"type": "string"},
            "reply": {"type": "string"},
        },
        "required": ["intent", "reasoning", "reply"],
        "additionalProperties": False,
    }

    def __init__(self, model_name: str = "claude-haiku-4-5"):
        """
        Requires ANTHROPIC_API_KEY to be set (env var or .env file).
        """
        self.model_name = model_name
        self.client = AsyncAnthropic()

    async def classify(self, conversation_history, user_query) -> dict:
        try:
            response = await self.client.messages.create(
                model=self.model_name,
                # 800 -- generous enough for a short real code snippet (SNIPPET's
                # "reply"), while still far below the Planner's own 16000 budget.
                # CHAT/TICKET replies are much shorter but share this one call.
                max_tokens=800,
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": self._schema,
                    }
                },
                system=[
                    {
                        "type": "text",
                        "text": self.classify_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Conversation history:\n{conversation_history}\n\n"
                            f"Latest user message:\n{user_query}"
                        ),
                    }
                ],
            )

            if response.stop_reason == "refusal":
                raise RuntimeError(f"Intent classification refused: {response.stop_details}")

            raw = next(block.text for block in response.content if block.type == "text")
            return json.loads(raw)
        except Exception as e:
            logger.error(f"Error classifying intent: {e}")
            # Fail safe toward TICKET -- worst case the Planner sees a chit-chat
            # message and makes an assumption about it (its job either way);
            # failing safe toward CHAT could silently drop a real request.
            return {
                "intent": "TICKET",
                "reasoning": "Classification call failed; defaulting to TICKET so a real "
                "request is never silently dropped.",
                "reply": "",
            }
