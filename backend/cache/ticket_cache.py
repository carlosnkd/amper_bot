"""
In-memory cross-turn store for the ticket pipeline, mirroring the pattern already used
by backend/cache/conversation_cache.py for chat messages.

Keyed by conversation_id only (not (user_id, conversation_id)) since a ticket pipeline
run is scoped to one conversation regardless of which user_id is driving it. Swap this
for a real table (mirroring how conversation_cache is flushed to `messages` in
backend/services/chat.py::end_conversation) if turns need to survive a process restart.
"""

from collections import defaultdict

_ticket_history_cache = defaultdict(list)


def get_ticket_history(conversation_id: str) -> list[dict]:
    return _ticket_history_cache.get(conversation_id, [])


def append_ticket_turn(conversation_id: str, turn: dict) -> None:
    _ticket_history_cache[conversation_id].append(turn)


def clear_ticket_history(conversation_id: str) -> None:
    _ticket_history_cache.pop(conversation_id, None)
