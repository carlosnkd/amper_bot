"""
Bridges CrewAI's event bus to a per-request queue of plain-dict progress events, so the
/build/stream SSE endpoint can forward them to the browser live while the (blocking) crew
pipeline runs on a background thread -- instead of the caller waiting on one big response.

Uses the same ContextVar-scoping trick as tools.py's _active_workspace: the event bus
snapshots the emitting thread's context (contextvars.copy_context()) before running
handlers, so a ContextVar set just before kickoff correctly routes each event back to the
request that triggered it, even though handlers themselves run in the event bus's own
thread pool. Handlers are registered once at import time; nothing here is per-request
except the ContextVar's value.
"""

import contextvars
import queue
from typing import Any

from crewai.events.event_bus import crewai_event_bus
from crewai.events.types.tool_usage_events import (
    ToolUsageFinishedEvent,
    ToolUsageStartedEvent,
)

_active_queue: contextvars.ContextVar["queue.Queue[dict] | None"] = contextvars.ContextVar(
    "active_progress_queue", default=None
)

# Tools whose *arguments* are worth announcing before they run -- write_file's finished
# event (with the file's full content) is published separately, as a "file" event.
_ANNOUNCE_TOOL_START = {
    "write_file": lambda args: f"Writing {args.get('relative_path', '...')}…",
    "read_file": lambda args: f"Reading {args.get('relative_path', '...')}…",
    "list_files": lambda _args: "Checking the workspace…",
    "run_python_syntax_check": lambda _args: "Running the syntax check…",
}


def set_active_queue(q: "queue.Queue[dict] | None") -> None:
    _active_queue.set(q)


def publish(event: dict[str, Any]) -> None:
    """Push a progress event for whichever request currently owns the active queue."""
    q = _active_queue.get()
    if q is not None:
        q.put(event)


def publish_phase(label: str) -> None:
    publish({"type": "phase", "label": label})


def _tool_args(event: Any) -> dict:
    args = getattr(event, "tool_args", None)
    return args if isinstance(args, dict) else {}


@crewai_event_bus.on(ToolUsageStartedEvent)
def _on_tool_started(source: Any, event: ToolUsageStartedEvent) -> None:
    label_fn = _ANNOUNCE_TOOL_START.get(event.tool_name)
    if label_fn:
        publish_phase(label_fn(_tool_args(event)))


@crewai_event_bus.on(ToolUsageFinishedEvent)
def _on_tool_finished(source: Any, event: ToolUsageFinishedEvent) -> None:
    if event.tool_name != "write_file":
        return
    args = _tool_args(event)
    path = args.get("relative_path")
    content = args.get("content")
    if path is not None and content is not None:
        publish({"type": "file", "path": path, "content": content})
