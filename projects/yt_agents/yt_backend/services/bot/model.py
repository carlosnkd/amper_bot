import os
import logging
from pathlib import Path
from dotenv import load_dotenv

try:
    import vertexai
    from vertexai.generative_models import GenerativeModel, GenerationConfig, Part, GenerationResponse
    from google.auth import default
except Exception:  # pragma: no cover - optional dependency fallback
    vertexai = None
    GenerativeModel = None
    GenerationConfig = None
    Part = None
    GenerationResponse = None
    default = None

load_dotenv()
logger = logging.getLogger(__name__)


class BotModel:
    """
        A class to handle interactions with the Gemini model for generating responses.

        This class provides methods to initialize the Gemini Model and generate responses for given context.
        Attributes:
            cretentials(google.auth.credentiales.Credentials): The credentials for auth with google cloud
            project_id(str): The google cloud project id
            location(str): The location of the Gemini model
            model(GenerativeModel): The Gemini model instance
    """
    def __init__(
        self,
        model_name="gemini-2.0-flash",
        system_instructions: str = None,
        location: str = "us-east4"
        ):

        self.model = None
        self.generation_config = None
        self.project = os.getenv("PROJECT_ID")

        if default is None or vertexai is None or GenerativeModel is None or GenerationConfig is None or Part is None:
            logger.warning("Vertex AI dependencies are not available; falling back to a non-network mode.")
            return

        try:
            self.credentials, self.project = default()
            vertexai.init(project=self.project, credentials=self.credentials, location=location)
            self.model = GenerativeModel(
                model_name=model_name,
                system_instruction=(Part.from_text(system_instructions) if system_instructions else None)
            )
            self.generation_config = GenerationConfig(
                max_output_tokens=15,
                temperature=0.7,
                top_p=0.9,
                top_k=32,
                response_mime_type="application/json"
            )
        except Exception as exc:
            logger.warning("Unable to initialize Vertex AI client: %s", exc)

    async def generate(self, contents):
        if self.model is None:
            return type("Response", (), {"text": "Vertex AI is unavailable in this environment. The UI can still be used, but research responses will be limited."})()

        result = await self.model.generate_content_async(
            contents=contents,
            generation_config=self.generation_config
        )
        return result
