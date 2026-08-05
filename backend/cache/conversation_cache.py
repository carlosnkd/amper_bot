from collections import defaultdict
from datetime import datetime

conversation_cache = defaultdict(list)

def add_message(user_id, conversation_id, role, content):
    conversation_cache[(user_id, conversation_id)].append({
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat()
    })

def get_conversation(user_id, conversation_id):
    return conversation_cache.get((user_id, conversation_id), [])

def clear_conversation(user_id, conversation_id):
    conversation_cache.pop((user_id, conversation_id), None)
