from anthropic import AsyncAnthropic
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO
)

class Summary:
    summary_prompt = """
    You are a virtual AI assistant specializing in summarizing conversations.

    Before responding, always consider the full context of the conversation along with the user's latest query to ensure an accurate and relevant response.

    **Task**:
    Generate a short, clear, and meaningful title that summarizes the main topic or intent of the conversation.
    The title will be displayed in the application's left-side conversation history panel.

    **Response Structure** (STRICT):
    - Return a JSON object only.
    - Output EXACTLY one JSON object.
    - The JSON must contain a single key: "title".
    - The value should be a concise string (3-8 words recommended).
    - DO NOT include any text before or after the JSON object.
    - Do NOT include explanations, formatting, markdown, or additional text.
    - Do NOT include emojis unless they are essential to the topic.
    - Do NOT truncate the JSON.
    - DO NOT include multiple JSON.
    - Capitalize appropriately (Title Case preferred).
    - Specific enough to distinguish this conversation from others.
    - The response MUST start with '{' and end with '}' to ensure it is valid JSON.

    **Example JSON response**:
    Response:
    {
        "title": "Python API Integration Help"
    }

    **Important Notes:**
    - Focus on the primary topic of objective of the conversation.
    - Use 3-8 words to create a concise and informative title.
    - If multiple topics are discussed, prioritize the most recent or dominant one.
    - The title must reflect the primary subject of the conversation.
    - Avoid vague titles such as "Question" or "Help Needed".
    - Avoid generic titles like "Chat with AI" or "Conversation".
    - Use keywords that would help users quickly identify this conversation in a list of conversations.
    - Avoid overly long titles.
    - Focus on clarity, specificity, and relevance.
    - If multiple topics are discussed, prioritize the most recent or dominant one.
    - Always output valid JSON.
    """

    # JSON schema enforced via output_config.format below -- guarantees a single
    # valid JSON object back, so the strict-JSON instructions above are a
    # (redundant but harmless) belt-and-suspenders on top of the schema.
    _title_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"}
        },
        "required": ["title"],
        "additionalProperties": False
    }

    def __init__(
            self,
            model_name: str = "claude-haiku-4-5"
            ):
        """
        Initializes the Summary class with an Anthropic (Claude) client.
        Requires ANTHROPIC_API_KEY to be set (env var or .env file); no
        Vertex/GCP credentials needed.
        """
        self.model_name = model_name
        self.client = AsyncAnthropic()
        print("Summary class initialized")

    async def generate_summary(self, conversation_history, user_query):
        try:
            # Haiku 4.5 doesn't support the `thinking`/`effort` params (they
            # error on this model tier), so this is a plain, single-shot call
            # constrained to a JSON object via output_config.format.
            response = await self.client.messages.create(
                model=self.model_name,
                max_tokens=300,
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": self._title_schema
                    }
                },
                system=[
                    {
                        "type": "text",
                        "text": self.summary_prompt,
                        "cache_control": {"type": "ephemeral"}
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Conversation history:\n{conversation_history}\n\n"
                            f"Latest user query:\n{user_query}"
                        )
                    }
                ]
            )

            if response.stop_reason == "refusal":
                raise RuntimeError(f"Summary generation refused: {response.stop_details}")

            summary_text = next(
                block.text for block in response.content if block.type == "text"
            )
            return summary_text
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            raise e
