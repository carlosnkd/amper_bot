import uuid
from backend.main import get_db
from fastapi import APIRouter, UploadFile, File, Depends
from typing import Optional
from backend.services.research import run_query
from sqlalchemy.orm import Session
from backend.services.chat import (
    record_message,
    end_conversation,
    load_user_history,
    delete_conversation
)
from agents.ticket_pipeline.main import run_ticket_pipeline

router = APIRouter()

@router.post('/run')
async def run_agent(
    user_id: str,
    query: str,
    file: Optional[UploadFile] = File(None),
    conversation_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    if file:
        pass

    result, summary = run_query()

    record_message(user_id, conversation_id, "user", query)
    record_message(user_id, conversation_id, "assistant", result)
    end_conversation(user_id, conversation_id, db, summary)

    return {"result": result}

@router.post('/run_ticket')
async def run_ticket(
    user_id: str,
    ticket: str,
    conversation_id: Optional[str] = None,
    max_retries: int = 3,
    db: Session = Depends(get_db)
):
    """
    Runs one turn of the Planner -> Coder -> Reviewer pipeline against `ticket`.
    Reuses the same conversation_id/history plumbing as /run so a follow-up ticket
    ("agrégale también X") on the same conversation is treated as an iteration.
    """
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    result = await run_ticket_pipeline(ticket, conversation_id, max_retries=max_retries)

    summary_text = result.get("code_summary") or result.get("error") or "No result"
    record_message(user_id, conversation_id, "user", ticket)
    record_message(user_id, conversation_id, "assistant", summary_text)
    end_conversation(user_id, conversation_id, db, summary_text[:120])

    return result

@router.post('/end_conversation')
def end_chat(user_id: str, conversation_id: str, db: Session = Depends(get_db)):
    return end_conversation(user_id, conversation_id, db)

@router.get('/get_history')
def history(user_id: str, db: Session = Depends(get_db)):
    return load_user_history(user_id, db)

@router.delete('/delete_conversation')
def delete_conversation_endpoint(conversation_id: str, db: Session = Depends(get_db)):
    return delete_conversation(conversation_id, db)
