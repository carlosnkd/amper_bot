import asyncio

from crewai import Crew
from crewai.process import Process
from research_agents.research.tasks import intent_task, research_task, query_builder_task, query_execute_task
from research_agents.research.agent import intent_classifier_agent, research_agent, query_builder_agent, query_execute_agent
from research_agents.research.flow import ResearchFlow
import pandas as pd
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

async def run_research(query: str):
    """
    Takes the user query and a file as an input and runs the research agent to get the answer.
    Args:
        df (pd.DataFrame): The input data as a pandas DataFrame.
        query (str): The research question to be answered.
    Returns:
        result (str): The answer to the research question.
        sql_query (str | None): The SQL query used to answer the question, if any was run.
    """
    try:
        flow = ResearchFlow()
        result = await flow.kickoff_async(inputs={'query': query})
        return result, flow.state.sql_query
    except Exception as e:
        logger.error(f"Error running research flow: {e}")
        return None, None


def run_research_example():
    return "Example of a result"

def query_summary(messages):
    """
    Gets the user query as an input and returns a summarized version of the query.
    """
    messages = json.dumps(messages)
    return f"Returned from query_summary"



if __name__ == "__main__":
    result, sql_query = asyncio.run(run_research("What is the average answer rate when we receive less than 200 calls?"))
    print("=="*20)
    print(f"Research Completed. Result: {result}")
    print(f"SQL used: {sql_query}")
    print("=="*20)
