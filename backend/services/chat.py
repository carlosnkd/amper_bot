import json
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.cache.conversation_cache import (
    add_message,
    clear_conversation,
    get_conversation
)
from backend.db import SessionLocal
import logging
logger = logging.getLogger(__name__)


def get_user_history(db: Session, user_id: str="carlos"):
    """
    Retrieves the history of queries for a given user.
    Args:
        username (str): The user identifier."""

    result = db.execute(
        text("SELECT history FROM users_history WHERE user_id = :user_id"),
        {"user_id": user_id}
    )
    return result.mappings().all()


def append_history(db: Session, username: str = "carlos"):
    """
    Appends a new query to the user's history.
    Args:
        username (str): The user identifier.
        query_summary (str): A summary of the query.
        query_details (str): Detailed information about the query.
    """
    result = db.execute(
        text("INSERT INTO users_history (user_id, history) VALUES(:user_id, :history)"),
        {"user_id": username, "history": "Sample history data"}
    )
    return result

def record_message(user_id, conversation_id, role, content, attachments=None, files=None):
    add_message(user_id, conversation_id, role, content, attachments=attachments, files=files)


def end_conversation(user_id, conversation_id, db, summary):
    messages = get_conversation(user_id, conversation_id)
    if not messages:
        return {"status": "nothing to save"}


    db.execute(
        text("""
        INSERT INTO messages (user_id, conversation_id, messages, summary, created_at)
        VALUES (:user_id, :conversation_id, :messages, :summary, :created_at)
        """),
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "messages": json.dumps(messages),
            "summary": summary,
            "created_at": datetime.now()
        }
    )
    db.commit()

    clear_conversation(user_id, conversation_id)

    return {"status": "conversation saved"}

def get_conversation_history(user_id, conversation_id):
    """
    Full persisted history for one conversation, oldest first -- the durable source of
    cross-turn context for the intent classifier / summarizer (see research.py's
    start_plan(), revise_plan(), etc.), as opposed to conversation_cache's get_conversation(),
    which only ever holds messages from the CURRENT, not-yet-flushed turn: end_conversation()
    clears that cache after every single call, so anything reading it for "history so far"
    would see nothing from prior turns even within the same conversation_id.

    Every turn is persisted as its own row (see end_conversation()), so a multi-turn
    conversation has multiple rows here -- this concatenates all of them in chronological
    order. Opens its own short-lived session rather than requiring the caller's
    request-scoped one, so it's safe to call from anywhere, including
    build_from_plan_worker's background thread, which doesn't share the request's
    SQLAlchemy Session.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""SELECT messages FROM messages
                     WHERE user_id = :user_id AND conversation_id = :conversation_id
                   ORDER BY created_at ASC"""),
            {"user_id": user_id, "conversation_id": conversation_id}
        )
        history = []
        for row in rows.mappings():
            history.extend(json.loads(row['messages']))
        return history
    finally:
        db.close()


def record_trace(user_id, conversation_id, turn_id, steps):
    """
    Persists one turn's worth of agent-decision steps, one row per step, all sharing
    `turn_id` -- that's what lets get_trace() regroup them back into the same card group
    the trace panel renders as a single chat turn, independent of the `messages`
    conversation history. Safe to call more than once for the same turn_id (e.g.
    start_plan() records INTENT immediately, then PLANNER once the Planner finishes) --
    rows just accumulate under that turn_id in call order. Never shown in the chat
    transcript itself -- see routes.py's GET /trace for how it's read back.

    Opens its own short-lived session rather than requiring the caller's request-scoped
    one, same reasoning as get_conversation_history: start_plan()/build_from_plan() (and
    build_from_plan_worker's background thread) don't have one to reuse.

    No-ops on an empty step list (e.g. a Planner call that raised before recording
    anything) so there's nothing to filter back out on read.
    """
    if not steps:
        return
    db = SessionLocal()
    try:
        db.execute(
            text("""
            INSERT INTO agent_traces
                (user_id, conversation_id, turn_id, agent, decision, reasoning, timestamp)
            VALUES
                (:user_id, :conversation_id, :turn_id, :agent, :decision, :reasoning, :timestamp)
            """),
            [
                {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "turn_id": turn_id,
                    "agent": step.get("agent"),
                    "decision": step.get("decision"),
                    "reasoning": step.get("reasoning"),
                    "timestamp": step.get("timestamp"),
                }
                for step in steps
            ],
        )
        db.commit()
    finally:
        db.close()


def get_trace(user_id, conversation_id):
    """
    Every persisted agent-trace step for one conversation, grouped by the chat turn it
    belongs to (turn_id) -- the full read side of record_trace(). Turns come back in
    chronological order (each turn's own steps in order too), as:

        [{"turn_id": "...", "steps": [{"agent", "decision", "reasoning", "timestamp"}, ...]}, ...]

    Grouping happens by iterating rows already sorted by timestamp and keying into a
    dict -- relies on Python dicts preserving insertion order, so the first time a
    turn_id is seen fixes that turn's position in the result.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            text("""SELECT turn_id, agent, decision, reasoning, timestamp FROM agent_traces
                     WHERE user_id = :user_id AND conversation_id = :conversation_id
                   ORDER BY timestamp ASC"""),
            {"user_id": user_id, "conversation_id": conversation_id},
        )
        turns: dict[str, dict] = {}
        for row in rows.mappings():
            turn = turns.setdefault(row["turn_id"], {"turn_id": row["turn_id"], "steps": []})
            turn["steps"].append(
                {
                    "agent": row["agent"],
                    "decision": row["decision"],
                    "reasoning": row["reasoning"],
                    "timestamp": row["timestamp"],
                }
            )
        return list(turns.values())
    finally:
        db.close()


def load_user_history(db, user_id):
    # ASC so that, within a conversation, earlier turns' messages get extend()-ed in
    # before later ones -- a DESC fetch (as this used to be) reads the newest row
    # first, so a multi-turn conversation would replay with its most recent exchange
    # FIRST and its opening message last. Conversations themselves are still shown
    # newest-first in the sidebar -- that's the final sort below, kept separate from
    # message order within each one.
    rows = db.execute(
        text("""SELECT conversation_id, summary, messages, created_at
               FROM messages
             WHERE user_id = :user_id
             ORDER BY created_at ASC"""),
        {"user_id": user_id}
    )
    history = {}
    for row in rows.mappings():
        cid = row['conversation_id']

        if cid not in history:
            history[cid] = {
                'conversation_id': cid,
                'summary': row['summary'],
                'messages': [],
                'last_activity': row['created_at'],
            }

        history[cid]['messages'].extend(
            json.loads(row['messages'])
        )
        # Keep overwriting as later (chronologically newer) rows come in, so the
        # conversation ends up with its MOST RECENT row's summary/timestamp, not its
        # first turn's -- matches the old DESC-fetch behavior's intent, just reached
        # by tracking "last seen" instead of "first seen" now that the fetch is ASC.
        history[cid]['summary'] = row['summary']
        history[cid]['last_activity'] = row['created_at']

    ordered = sorted(history.values(), key=lambda c: c['last_activity'], reverse=True)
    for conversation in ordered:
        del conversation['last_activity']

    return {'history': ordered}

def delete_conversation(user_id, db, conversation_id):
    db.execute(
        text("""DELETE FROM messages
             WHERE conversation_id = :conversation_id AND
             user_id = :user_id
            """),
            {"conversation_id": conversation_id,
             'user_id': user_id}
    )

    db.commit()
    return {"status": "deleted"}
# def get_conversation(db, conversation_id):
#     rows = db.execute(
#         text("""SELECT messages FROM messages
#                  WHERE conversation_id = :conversation_id"""),
#         {'conversation_id':conversation_id}
#     )
#     return rows.mappings().all()
