from collections import defaultdict
from datetime import datetime

conversation_cache = defaultdict(list)

def add_message(user_id, conversation_id, role, content, attachments=None, files=None):
    message = {
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat()
    }
    # Omitted entirely (not even as None/[]) when there's nothing attached, so the vast
    # majority of messages that never had a file keep their old, smaller shape -- only
    # turns that actually had an upload carry the extra key. See backend/api/routes.py's
    # _extract_attachment() for what one entry looks like.
    if attachments:
        message["attachments"] = attachments
    # Same reasoning as attachments above -- only a build turn that actually wrote files
    # carries this key. `files` is a list of workspace-relative paths (see /build/stream
    # in backend/api/routes.py); content isn't stored here, GET /workspace_file reads it
    # back off disk on demand when a replayed file chip is clicked.
    if files:
        message["files"] = files
    conversation_cache[(user_id, conversation_id)].append(message)

def get_conversation(user_id, conversation_id):
    return conversation_cache.get((user_id, conversation_id), [])

def clear_conversation(user_id, conversation_id):
    conversation_cache.pop((user_id, conversation_id), None)
