
import logging
from agents.research.flow import ResearchFlow

logger = logging.getLogger(__name__)
async def run_research(query:str):
    """
    Takes the user query as an input an runs the research agent to generate a response.
    Args:
        query (str): The research question to be answered.
    Returns:
        result (str): The answer to the research question.
    """
    try:
        flow = ResearchFlow()
        result = await flow.kickoff_async(inputs={'query': query})
        return result
    except Exception as e:
        logger.error(f"Error running research flow: {e}")
