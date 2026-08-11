from crewai import Agent, LLM
from research_agents.research.tools import search_tool, query_database, get_schema_info
import os
from langchain_google_genai import ChatGoogleGenerativeAI
import json

from dotenv import load_dotenv
from pathlib import Path

load_dotenv()
API_KEY = os.getenv("SERPER_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

workspace_root = Path(__file__).resolve().parents[2]
credential_path = Path(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or workspace_root / "agentic-ai-project-485616-eb1a03e20e28.json")

if credential_path.exists():
    with credential_path.open("r", encoding="utf-8") as file:
        vertex_credentials = json.load(file)
else:
    vertex_credentials = {}

# Convert the credentials to a JSON string
vertex_credentials_json = json.dumps(vertex_credentials)

llm=ChatGoogleGenerativeAI(model='gemini-flash-lite-latest',
                           verbose=True,
                           temperature=0.5,
                           google_api_key=GOOGLE_API_KEY,
                           vertexai=True,
                           project=os.getenv("PROJECT_ID"))

llm = LLM(
    model="gemini-flash-lite-latest",
    temperature=0.5,
    vertex_credentials=vertex_credentials_json
)

intent_classifier_agent = Agent(
    role='Intent Classifier',
    goal="""Given a user query your job is to identify the users intent and classify it into one of the following categories:
            1. Data Analysis/Data Question: The user is asking for insights, patterns, or specific information from the data.
            2. Explanation question: The user is asking for an explanation about a concept, method, or result related to data analysis.
            3. Small talk: The user is engaging in casual conversation or asking questions that are not related to data analysis.
            4. Other: The user is asking for something that does not fit into the previous categories.

        Return only the word or phrase that best fits the user's intent, without any additional explanation or text.
    """,
    backstory="""
        You are an expert in understanding user intent and classifying it into specific categories.
        Your specialty is to analyze user queries and determine the underlying intent behind them.
    """,
    verbose=True,
    tools = [], #Just classifies, no tools needed
    llm=llm,
    allow_delegation=False,

)

research_agent = Agent(
        role='Database analyst',
        goal="""
                Given a database, your job is to extract columns, analyze data structure.""",
        backstory="""
                    You are an experienced analyst with expertise in gathering and
                    analyzing information from various sources.""",
        verbose=True,
        tools=[get_schema_info], #Just analyzes
        llm=llm,
        allow_delegation=False # Allow the agent to delegate tasks to other agents. Default is False.
    )

validate_agent = Agent(
        role='Validate Agent',
        goal='Given a database and a user query your job is to evaluate if the query can be answered with the available data.',
        backstory='You are skilled in evaluating the relevance and adequacy of data to answer specific queries.',
        verbose=True,
        tools=[],
        llm=llm,
        allow_delegation=False
    )

query_builder_agent = Agent(
        role='Task Builder',
        goal='Create a task for the query agent',
        backstory="""
            You are an expert into breaking down complex goals into manageable tasks.
            Your specialty is to get insights from data, you are very skilled on how to get the best out of data.
            Your inputs are:
            1. A txt file with the description of the data in following format:
                'ColumnName: DataType - Description/Notes'
            2. A user query asking for specific information from the data.
                You might need to create multiple queries to get the information needed.
                You might need to create some calculations to have the final answer.
            Your main goal is to create a query or a series of queries that allow the query agent to
            have the information the user is asking for.
            The queries should be as specific as possible to get the data, the user should only need to run the query,
            assume the database used is a PostgreSQL database.
                """,
        verbose=True,
        allow_delegation=False,
        tools=[search_tool, query_database],
        llm=llm
    )

query_execute_agent = Agent(
        role='Query Agent',
        goal='Answer queries based on the research findings',
        backstory='You are skilled in extracting information and answering questions.',
        verbose=True,
        allow_delegation=False,
        tools=[search_tool],
        llm=llm
    )
