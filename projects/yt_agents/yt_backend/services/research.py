from fastapi import logger
from research_agents.research.main import run_research, query_summary, run_research_example
from yt_backend.services.bot.summary import Summary
import logging
import json
logger = logging.getLogger(__name__)

summaryClass = Summary()

async def run_query(query):
    # result = run_research_example()
    # summary = query_summary(query)

    result, sql_query = await run_research(query)
    summary = await summaryClass.generate_summary("", query)
    return result, summary, sql_query
