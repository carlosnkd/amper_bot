from crewai import Task
from agents.research.agent import research_agent, query_builder_agent, intent_classifier_agent, validate_agent  


intent_task = Task(
    name="Intent Classification Task",
    description="""
        Classify the user's intent into one of the following categories: {query}
            1. Data Analysis/Data Question: The user is asking for insights, patterns, or specific information from the data.
            2. Explanation question: The user is asking for an explanation about a concept, method, or result related to data analysis.
            3. Small talk: The user is engaging in casual conversation or asking questions that are not related to data analysis.
            4. Other: The user is asking for something that does not fit into the previous categories.
    """,
    expected_output="""
                    Classify the user query into exactly one of the following categories:
                    - DATA
                    - EXPLANATION
                    - SMALL_TALK
                    - OTHER
                    
                    You MUST respond in valid JSON format:
                    {
                    "intent": "<ONE_OF_THE_ALLOWED_VALUES>"
                    }
                    Do not include explanations.
                    Do not include extra text.
                    Only output valid JSON.""",
    agent=intent_classifier_agent,
    output_file="intent_classification.txt"
)

research_task = Task(
        name="Research Task",
        description=("Analyze the call center database and provide a comprehensive summary of the columns and data types"),
        expected_output="""Comprehensive summary of column names and values of each table in the database. The summary should be in the following format:
                        The goal here is to identify data types for each column and the 
                        relationships between tables for possible joins.
                        Print the output in following format as list:
                        Table: <Table Name>
                            - <ColumnName>: DataType
                        
                        Limit your response to the tables inside the data base.
                        DO NOT make assumptions about the data that are not supported by the actual data in the database.
                        DO NOT create columns that do not exist in the database.
                        DO NOT include explanations or extra text.
                        """,
        agent=research_agent,
        async_execution=False,
        context=[intent_task],
        output_file=f"Database_schema.txt"
    )

validate_task = Task(
    name="Validate Task",
    description="""Analyze the summary of the database and the user query: {query}""",
    expected_output= """ 
                        Evaluate the query and the info available in one of the following categories:
                        1. Direct Answer: The query can be answered with the data available
                        2. Indirect Answer: The query cannot be answered with the data available, but we can get insights from the data that might help answer the query.
                        3. No Answer: The query cannot be answered with the data available, and we cannot get insights
                        
                        You MUST respond in valid JSON format:
                        {
                            "validation": "<ONE_OF_THE_ALLOWED_VALUES>"
                        }
                        Do not include explanations.
                        Do not include extra text.
                        Only output valid JSON.""",
    agent=validate_agent,
    async_execution=False,
    context=[research_task],
    output_file=f"validation.txt"
)
 
query_builder_task = Task(
        name="Query Builder Task",
        description="""Using the column names and data types from the db in the previous analysis, 
        create a query or a series of queries to answer the following user query:
                        {query}""",
        expected_output="Query or series of queries to answer the user query.",
        agent=query_builder_agent,
        async_execution=False,
        context=[research_task],
        output_file="query_builder.txt"
    )

query_execute_task = Task(
        name="Query Execution Task",
        description="Execute the query or series of queries from the previous task and return the results.",
        expected_output="The results from the query execution.",
        agent=query_builder_agent,
        async_execution=False,
        context=[query_builder_task],
        output_file="final_answer.txt"
        )