from agents.ticket_pipeline.main import run_ticket_pipeline
from backend.services.bot.summary import Summary

summaryClass = Summary()

def run_query():
    result = await run_ticket_pipeline(ticket, conversation_id, max_retries=max_retries)
    summary = await summaryClass.generate_summary(ticket, conversation_id)
    return result, summary
