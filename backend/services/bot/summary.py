from backend.services.bot.model import BotModel
import logging 

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

    def __init__(
            self, 
            model = BotModel
            ):
        """
        Initializes the Summary class with a BotModel instance.
        """
        self.model = BotModel(system_instructions=self.summary_prompt)
        print("Summary class initialized")
    
    async def generate_summary(self, conversation_history, user_query):
        try:
            summary = await self.model.generate(contents=[conversation_history, user_query])
            return summary.text
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            raise e
        
    
