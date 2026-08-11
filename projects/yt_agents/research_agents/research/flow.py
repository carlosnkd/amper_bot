import json
from crewai import Crew, Process
from crewai.flow.flow import Flow, start, router, listen
from pydantic import BaseModel
from typing import Optional
from research_agents.research.agent import intent_classifier_agent, research_agent, query_builder_agent, query_execute_agent, validate_agent
from research_agents.research.tasks import intent_task, research_task, query_builder_task, query_execute_task, validate_task
import logging

class ResearchState(BaseModel):
    query: Optional[str] = None
    intent: Optional[str] = None
    validation: Optional[str] = None
    final_results: Optional[str] = None
    sql_query: Optional[str] = None
    error: Optional[str] = None


class ResearchFlow(Flow[ResearchState]):
    @start()
    def classify_intent(self):
        try:
            intent_crew = Crew(
                agents=[intent_classifier_agent],
                tasks=[intent_task],
                process=Process.sequential,
                memory=True,
                verbose=True,
            )
            result = intent_crew.kickoff(inputs={'query': self.state.query})
            result = result.raw
            result = json.loads(result)
            self.state.intent = result['intent']
            print(f"Classified intent: {self.state.intent}")
            return self.state.intent

        except Exception as e:
            logging.error(f"Error in classify_intent")
            self.state.error = f"Error in classify_intent"

    @router(classify_intent)
    def route_intent(self):
        intent = self.state.intent or ""
        if self.state.intent == "DATA":
            return "Data"
        else:
            return "No data"

    @listen("Data")
    def data_intent(self):
        try:
            research_crew = Crew(
            #If the intent is data related it analyze the database and the query to understand if we can answer the question with the data available,
            # if not we should be able to give insights about the data that might help answer the question.
                    agents=[research_agent, validate_agent],
                    tasks=[research_task, validate_task],
                    process=Process.sequential,
                    memory=True,
                    verbose=True
            )
            intent_results = research_crew.kickoff(inputs={'query': self.state.query})
            intent_results = intent_results.raw
            intent_results = json.loads(intent_results)
            print(f"Validation results: {intent_results}")
            self.state.validation = intent_results['validation']
            self.state.final_results = self.state.validation
            return self.state.final_results

        except Exception as e:
            logging.error(f"Error in data_intent: {e}")
            self.state.error = f"Error in data_intent: {e}"

    @listen("No data")
    def no_data_intent(self):
        self.state.final_results = """
        The user's query does not seem to be related to data analysis or explanation.
        No further action will be taken."""
        return self.state.final_results

    @router(data_intent)
    def route_data_intent(self):
        self.state.validation = self.state.validation or ""
        if self.state.validation == "Direct Answer":
            return "Build Query"
        else:
            return "End Flow"

    @listen("Build Query")
    def build_query(self):
        try:
            query_crew = Crew(
                    agents=[query_builder_agent, query_execute_agent],
                    tasks=[query_builder_task, query_execute_task],
                    process=Process.sequential,
                    memory=True,
                    verbose=True
            )
            raw_final_results = query_crew.kickoff(inputs={'query': self.state.query})
            raw_final_results = raw_final_results.raw
            print(f"Raw final results: {raw_final_results}")
            self.state.final_results = raw_final_results
            if query_builder_task.output:
                self.state.sql_query = query_builder_task.output.raw
            return self.state.final_results
        except Exception as e:
            logging.error(f"Error in build_query: {e}")
            self.state.error = f"Error in build_query: {e}"

    @listen("End Flow")
    def end_flow(self):
        return "Returned from end_flow"
    # Code to return either a response with insights about the data or a message indicating that the query cannot be answered with the available data.
