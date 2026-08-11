from fastapi import APIRouter, UploadFile, File, Form, Depends
from sqlalchemy.orm import Session
from yt_backend.main import get_db
from yt_backend.services.chat import (
    record_message,
    load_user_history,
    end_conversation,
    delete_conversation,
)
from yt_backend.services.research import run_query
import uuid
import json
from pathlib import Path
import logging
from typing import Optional

# Only importable when this app is mounted in-process inside the amper_bot host
# (backend/app.py adds projects/yt_agents to sys.path -- see that file), which is
# the only way this app is deployed. Mirrors Coddy's own backend/api/routes.py:
# a router-wide "any granted session" gate, plus "full" required on mutating
# routes below, so a guest session (see backend/access.py) can look around
# read-only but not touch the data.
from backend.access import require_any, require_full

logger = logging.getLogger(__name__)

#This file defines what the app can do
router = APIRouter(dependencies=[Depends(require_any("yt_agents"))])
_require_full = Depends(require_full("yt_agents"))
UPLOAD_DIR = Path("data")

@router.post("/run", dependencies=[_require_full])
async def run_agent(
    user_id: str = Form(...),
    file: Optional[UploadFile] = File(None),
    query: str = Form(...),
    conversation_id: str | None = Form(None),
    db: Session = Depends(get_db)
):
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    if file:
        pass

    result, summary, sql_query = await run_query(query)

    print("RAW SUMMARY:")
    print(summary)
    title = "Conversation"
    try:
        cleaned = summary.strip() if isinstance(summary, str) else ""
        if cleaned.startswith("{") and not cleaned.endswith("}"):
            cleaned += "}"
        title = json.loads(cleaned)["title"]
    except Exception:
        # The summarizer didn't return valid JSON (e.g. Vertex AI is
        # unavailable and a fallback message was returned instead). Fall
        # back to a generic title rather than failing the whole request --
        # the conversation must still be saved so it shows up in the
        # sidebar.
        logger.warning("Could not parse summary as JSON; using fallback title. Raw summary: %r", summary)
    summary = title

    record_message(user_id, conversation_id, "user", query)
    record_message(user_id, conversation_id, "assistant", result, sql_query=sql_query)
    end_conversation(user_id, conversation_id, db, summary)

    return {
        "conversation_id": conversation_id,
        # "summary": summary,
        "result": result,
        "sql_query": sql_query
    }

@router.post("/end_conversation", dependencies=[_require_full])
def end_chat(user_id: str, conversation_id: str, db: Session = Depends(get_db)):
    print(conversation_id)
    return end_conversation(user_id, conversation_id, db)

@router.get("/get_history")
def history(user_id: int=1, db: Session = Depends(get_db)):
    return load_user_history(db, str(user_id))

@router.delete("/delete_conversation", dependencies=[_require_full])
def delete_conversation_endpoint(conversation_id: str, user_id: int=1, db:Session=Depends(get_db)):
    return delete_conversation(user_id, db, conversation_id)

# #Endpoint to get the conversation shown in the UI
# @router.get("/get_conversation")
# def get_conversation_endpoint(message_id:str, db: Session = Depends(get_db)):
#     return get_conversation(message_id, db)
