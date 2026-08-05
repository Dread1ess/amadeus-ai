"""Per-user conversation history stored in memory."""

from typing import Dict, List

from config import MAX_HISTORY

# Per-user conversation history.
user_sessions: Dict[int, List[Dict[str, str]]] = {}


def get_user_history(user_id: int) -> List[Dict[str, str]]:
    """Return the chat history for a user, creating it if it does not exist."""
    if user_id not in user_sessions:
        user_sessions[user_id] = []
    return user_sessions[user_id]


def add_to_history(user_id: int, role: str, content: str) -> None:
    """Append a message to the user history and trim it to the allowed length."""
    history = get_user_history(user_id)
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY:
        user_sessions[user_id] = history[-MAX_HISTORY:]


def clear_history(user_id: int) -> None:
    """Reset the chat history for a user."""
    if user_id in user_sessions:
        user_sessions[user_id] = []
