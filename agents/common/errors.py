"""
Maps an exception from an LLM call to a short, user-safe message for the chat UI --
never the raw exception text, which can contain an SDK error's full JSON response body,
a request ID, or (for a malformed-JSON-from-the-model failure) the model's entire raw
output pasted verbatim. A user who typed "add a discount coupon validator" has no use
for `Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', ...`
sitting in their chat history.

Every call site using this should still log the original exception in full server-side
(logger.exception(...)) before calling it -- this function only decides what the END
USER sees, never what's debuggable.

Checked most-specific to least-specific -- every branch below was verified against the
actually-installed library source (crewai/anthropic/httpx/sqlalchemy under bot_env/),
not assumed from documentation or typical behavior:

  1. anthropic.APIStatusError -- real status_code/.type from the API response itself.
     Fires for every LLM call in this app, not just the ones that construct an
     AsyncAnthropic client directly (backend/services/bot/intent.py, summary.py):
     crewai's own Anthropic wrapper (crewai/llms/providers/anthropic/completion.py,
     used by agents/common/llm.py's Planner/Coder/Reviewer calls) just re-raises these
     unchanged on anything that isn't a context-length error -- verified by reading
     that wrapper's except blocks directly.
  2. anthropic.APIResponseValidationError -- a SIBLING of APIStatusError (both subclass
     APIError directly, neither is a parent of the other -- see anthropic/_exceptions.py),
     so it does NOT match the check above. Raised in anthropic/_base_client.py and
     _response.py when the response body doesn't match the SDK's expected schema, or
     has an unexpected content-type -- a real response came back, just not a shape the
     SDK can parse.
  3. anthropic.APIConnectionError (covers APITimeoutError, a subclass) -- a connection
     failure establishing the request. anthropic/_base_client.py's _request() wraps
     httpx.TimeoutException/any other exception raised by the initial client.send()
     into these -- but for a streaming call (every LLM call here uses stream=True, see
     agents/common/llm.py) that send() only receives HEADERS; the response body is
     read later by a separate code path with no such wrapping.
  4. httpx.TransportError -- the gap left by #3: anthropic/_streaming.py's SSE-event
     iteration (and crewai's `for event in stream:` loop reading it) has no try/except
     around it at all, so a connection that drops PARTWAY THROUGH a response raises a
     raw httpx exception (ReadError, RemoteProtocolError, ...), never rewrapped into
     anthropic.APIConnectionError. httpx is already a resolvable dependency (anthropic
     itself depends on it).
  5. crewai's own LLMContextLengthExceededError -- input too big for the model's
     context window (e.g. a huge uploaded file, or a very long conversation history).
  6. Python's builtin TimeoutError -- what crewai/agent/core.py's execute_task()
     raises (explicitly re-raised, not absorbed) when max_execution_time is exceeded.
     Not a crewai-specific class. Not currently reachable: agents/ticket_pipeline/
     agent.py doesn't set max_execution_time on any agent today, kept for whenever it
     is. max_iter exceeded is deliberately NOT a branch here -- verified in
     crewai/utilities/agent_utils.py's handle_max_iterations_exceeded(): it forces one
     more LLM call for a final answer and returns normally, it never raises. Whatever
     that forced answer turns out to be already lands in branch #8 below if it isn't
     valid JSON.
  7. sqlalchemy.exc.OperationalError / IntegrityError -- confirmed by actually
     triggering a locked-database error through this project's own SQLAlchemy engine:
     message is `"(sqlite3.OperationalError) database is locked"`. NOTE: as of this
     writing, backend/api/routes.py's record_message()/end_conversation() calls aren't
     inside any try/except, so this branch is correctly classified but not yet
     reachable from those call sites -- see the module's own follow-up note.
  8. agents/ticket_pipeline/flow.py's own _parse_json_output() ValueError, when the
     model's response wasn't valid JSON -- including an empty/malformed 200 response:
     verified in crewai's completion.py that response.content is always guarded
     (`if response.content:`) before being indexed, so an empty/unexpected response
     body never raises there, it just produces an empty string that lands here.
  9. CrewAI's Task-interpolation ValueError (see #1's sibling case, template
     variables) -- also just a plain ValueError, distinguished by message text since
     CrewAI doesn't give it its own exception class either.
  10. A generic catch-all for anything else (network blips, etc.).
"""

import logging

import anthropic
import httpx
import sqlalchemy.exc
from crewai.utilities.exceptions.context_window_exceeding_exception import (
    LLMContextLengthExceededError,
)

logger = logging.getLogger(__name__)


def friendly_error_message(exc: Exception) -> str:
    if isinstance(exc, anthropic.APIStatusError):
        return _anthropic_status_message(exc)

    if isinstance(exc, anthropic.APIResponseValidationError):
        return (
            "The AI service sent back a response that didn't match its expected "
            "format. Please try again in a moment."
        )

    # APITimeoutError is a subclass of APIConnectionError, so this covers both.
    if isinstance(exc, anthropic.APIConnectionError):
        return (
            "Couldn't reach the AI service right now (connection issue or timeout). "
            "Please try again in a moment."
        )

    # A mid-stream disconnect, NOT covered by the anthropic.APIConnectionError check
    # above -- see this module's docstring, item 4.
    if isinstance(exc, httpx.TransportError):
        return (
            "The connection to the AI service dropped partway through a response. "
            "Please try again."
        )

    if isinstance(exc, LLMContextLengthExceededError):
        return (
            "That request was too large for the AI model to process in one go (a very "
            "long conversation, or a large uploaded file). Try starting a new "
            "conversation, or trimming what you've attached."
        )

    # max_execution_time exceeded (not max_iter -- see this module's docstring, item 6,
    # for why that needs no branch here). Not currently reachable in this app -- kept
    # for whenever an agent sets max_execution_time.
    if isinstance(exc, TimeoutError):
        return (
            "The AI agent took too long working on this and was stopped. Please try "
            "again, or try breaking the ticket into a smaller request."
        )

    if isinstance(exc, (sqlalchemy.exc.OperationalError, sqlalchemy.exc.IntegrityError)):
        return _sqlalchemy_message(exc)

    text = str(exc)
    if "template variable" in text.lower() or "error interpolating" in text.lower():
        # crewai/task.py's interpolate_inputs_and_add_conversation_history() -- a
        # Task's description/expected_output/output_file has a {placeholder} with no
        # matching key in kickoff(inputs=...). Reachable here through
        # build_plan_task()'s revision_block if a previous plan's task description (or
        # the user's feedback text) happens to contain literal {word}-shaped text --
        # see tasks.py's own comment on that.
        return (
            "The AI couldn't build a plan for this request -- please try rephrasing "
            "your ticket."
        )

    if "did not return valid JSON" in text:
        # e.g. "Planner did not return valid JSON: '...the model's entire raw output...'"
        # -- keep the step name, drop everything after it, which can be arbitrarily long
        # and isn't meaningful to an end user anyway.
        step = text.split(" did not return valid JSON", 1)[0].strip()
        return f"{step or 'The AI'} returned a response that couldn't be understood. Please try again."

    return "Something went wrong talking to the AI model. Please try again in a moment."


def _anthropic_status_message(exc: anthropic.APIStatusError) -> str:
    body_message = ""
    if isinstance(exc.body, dict):
        error = exc.body.get("error")
        if isinstance(error, dict):
            body_message = str(error.get("message") or "")

    # "billing_error" is ErrorType's dedicated value for this, but a real credit-balance
    # response we've actually seen came back typed "invalid_request_error" instead with
    # "credit balance" in the message -- checking both rather than trusting .type alone.
    if exc.type == "billing_error" or "credit balance" in body_message.lower():
        return (
            "The AI service's account has run out of credits. This isn't something you "
            "can fix from the chat -- the account needs more credit added before this "
            "will work again."
        )
    if exc.status_code == 401 or exc.type == "authentication_error":
        return (
            "The AI service rejected the API key configured for this app. This is a "
            "setup issue, not something fixable from the chat -- the app's API key "
            "needs attention."
        )
    if exc.status_code == 429 or exc.type == "rate_limit_error":
        return (
            "The AI service is rate-limiting requests right now. Please wait a moment "
            "and try again."
        )
    if exc.status_code in (503, 529) or exc.type == "overloaded_error":
        return "The AI service is temporarily overloaded. Please try again in a moment."
    if exc.status_code >= 500:
        return "The AI service had an internal error. Please try again in a moment."
    return "The AI service rejected the request. Please try again, or rephrase your message."


def _sqlalchemy_message(exc: Exception) -> str:
    if isinstance(exc, sqlalchemy.exc.IntegrityError):
        return "This couldn't be saved due to a data conflict. Please try again."
    if "database is locked" in str(exc).lower():
        return (
            "The database is briefly busy handling another request. Please try again "
            "in a moment."
        )
    return "There was a problem saving this conversation. Please try again."
