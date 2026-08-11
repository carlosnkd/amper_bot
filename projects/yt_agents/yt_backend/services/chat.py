import json
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from yt_backend.cache.conversation_cache import (
    add_message,
    clear_conversation,
    get_conversation
)
import logging
from research_agents.research.main import query_summary
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

def record_message(user_id, conversation_id, query, response, sql_query=None):
    add_message(user_id, conversation_id, query, response, sql_query=sql_query)


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

def load_user_history(db, user_id):
    rows = db.execute(
        text("""SELECT conversation_id, summary, messages, created_at
               FROM messages 
             WHERE user_id = :user_id
             ORDER BY created_at DESC"""),
        {"user_id": user_id}
    )
    history = {}
    for row in rows.mappings():
        cid = row['conversation_id']

        if cid not in history:
            history[cid] = {
                'conversation_id':cid,
                "summary": row['summary'],
                "messages":[]
            }
        
        history[cid]['messages'].extend(
            json.loads(row['messages'])
        )


    return {'history':list(history.values())}

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