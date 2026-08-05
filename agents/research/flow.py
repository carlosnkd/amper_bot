import json
from crewai import Crew
from crewai.flow.flow import start, Flow
from pydantic import BaseModel
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class ResearchState(BaseModel):
    query: Optional[str] = None
    intent: Optional[str] = None
    validation: Optional[str] = None
    final_results: Optional[str] = None
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
            return self.state.intent
        except Exception as e:
            logging.error(f"Error in classify_intent: {e}")
            self.state.error = f"Error in classify_intent: {e}"
