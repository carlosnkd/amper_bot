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
    - CHAT    -- small talk, greetings, or questions about the assistant itself
      -- OR a general-knowledge/off-topic question (prices, sports, books,
      recipes, trivia, current events, anything not about code or this
      product). Both get a "reply" here, but the CONTENT differs sharply: see
      the "reply" rules below -- off-topic questions get a boundary-setting
      decline, never the actual answer.
    - SNIPPET -- a self-contained TECHNICAL/programming question or "write me
      a quick X" request that has nothing to do with modifying this product
      (e.g. "give me a simple FastAPI script", "how does Python's GIL work").
      Doesn't belong in the ticket pipeline either -- there's nothing of ours
      to plan or review -- but deserves a real, code-capable answer, not a
      chit-chat brush-off. Non-technical off-topic questions are CHAT, not
      this -- SNIPPET is reserved for programming/software-engineering asks.

    CHAT and SNIPPET are handled identically downstream (see start_plan() in
    backend/services/research.py): both skip the Planner entirely and this
    class's own "reply" is shown to the user directly. The distinction exists so
    the prompt/token budget can be tuned for "a sentence or two" (CHAT) vs
    "a short block of working code" (SNIPPET) without one bleeding into the other.

    This assistant is scoped to coding/planning work for this product, so CHAT's
    "reply" is deliberately two different behaviors under one label -- see the
    classify_prompt's "reply" rules for the boundary-setting decline that off-topic
    general-knowledge questions must get instead of a real answer.

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
    - "SNIPPET": a self-contained TECHNICAL/programming request that does NOT
      touch this product's codebase -- e.g. "write me a simple FastAPI
      hello-world script", "give me a regex for emails", "how do I reverse a
      linked list in Python". Nothing to plan or review here; just answer
      directly, with working code when code was asked for. Reserved for
      programming/software-engineering questions only -- general-knowledge
      questions (below) are CHAT, not this, even if they'd be quick to answer. For example:
        (a) What is OOP? -> intent: "SNIPPET" (a programming/CS
            concept question, even asked as a bare "what is X", belongs here -- it's
            not general trivia).
        (b) What is the capital of France? -> intent: "CHAT" (not a programming/CS
            concept, this is general trivia).
        (c) How do I reverse a linked list in Python? -> intent: "SNIPPET" (a programming question,
            even if it's a "how do I" phrasing, belongs here -- it's not general trivia).
        (d) What's the difference between SQL and NoSQL databases? -> intent: "SNIPPET"
        (a technical/software concept comparison -- "difference between X and Y"
        phrasing does NOT make it general trivia; it's still SNIPPET whenever
        X and Y are programming/software/CS concepts).
        Rule of thumb:
        if the subject matter itself is programming, software
        engineering, or CS (languages, frameworks, databases, architecture,
        algorithms, protocols, tooling, etc.), it's SNIPPET regardless of whether
        the question is phrased as "what is X", "difference between X and Y",
        "how does X work", or "explain X". CHAT(b) is reserved for subjects that
        aren't about code/software at all.
    - "CHAT": everything else. This covers two very different situations that
      share a label but NOT a reply style:
        (a) greetings, small talk, or questions about what this assistant can
            do or how it works -- answer these normally and warmly.
        (b) ANY general-knowledge, trivia, or off-topic question that has
            nothing to do with code, software, or this product -- prices,
            sports, recipes, books, movies, health/fitness, current events,
            history, translations of unrelated text, etc. This assistant is
            scoped to coding/planning work for this product ONLY. It must
            NEVER answer these, not even briefly or "just this once" -- no
            partial answer, no fact "by the way", nothing that resolves what
            was actually asked. Decline and redirect instead (see below).

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
    - "reply" is REQUIRED when intent is "SNIPPET" or "CHAT":
        - For SNIPPET: the actual answer, written as the assistant, with real,
          working code (in a markdown code block) plus at most a sentence or
          two of context -- don't pad it with unnecessary caveats.
        - For CHAT case (a) above (small talk / about the assistant): a short,
          direct, friendly answer; mention you can plan and build features or
          fixes when relevant.
        - For CHAT case (b) above (off-topic/general-knowledge): 1-2 sentences
          that (1) state plainly this is outside what you help with, and (2)
          redirect toward what you DO help with (planning/building features,
          fixes, or code for this product). Do NOT include the requested fact,
          estimate, opinion, or any partial version of it -- not even as an
          aside. Do not soften the decline by answering anyway. Reply in the
          same language the user wrote in.
          Example -- user: "what is the price of a big mac in mexico" ->
          reply: "I'm a coding assistant focused on planning and building
          features for this product, so I can't help with pricing lookups
          like that -- you'd want a currency/price site or McDonald's Mexico
          directly. Happy to help if you've got a coding or feature request
          though!"
          Example -- user: "de que se trata el libro dimelo bajito" -> reply
          (in Spanish, matching the user): "Soy un asistente de programacion
          enfocado en planear y construir funciones para este producto, asi
          que no puedo ayudarte con resumenes de libros. Si tienes una tarea
          de codigo o una funcion que quieras construir, ahi si te puedo
          ayudar."
    - "reply" MUST be an empty string when intent is "TICKET" -- the Planner
      handles that turn instead, not you.
    - No text before or after the JSON object.
    """

    _schema = {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string"},
            "intent": {"type": "string", "enum": ["TICKET", "SNIPPET", "CHAT"]},
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
