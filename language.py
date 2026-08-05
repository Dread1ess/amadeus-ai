"""Script detection used to reply in the user's language."""

from typing import Tuple

from memory import get_user_history


def _script_counts(text: str) -> Tuple[int, int]:
    """Return (cyrillic_count, latin_count) for the given text."""
    cyrillic_count = sum(1 for char in text if "\u0400" <= char <= "\u04ff")
    latin_count = sum(1 for char in text if char.isascii() and char.isalpha())
    return cyrillic_count, latin_count


def history_has_cyrillic(user_id: int) -> bool:
    """Return True if the user's recent history is written in Russian.

    Only the presence of Cyrillic counts, so the English "[Message from ...]:"
    prefix that wraps every stored user message can never bias the result.
    """
    for message in get_user_history(user_id):
        if message["role"] == "system":
            continue
        cyrillic_count, _ = _script_counts(message["content"])
        if cyrillic_count > 0:
            return True
    return False


def resolve_language(user_id: int, text: str) -> str:
    """Pick the reply language, keeping continuity with the conversation.

    A clearly Cyrillic message forces Russian. Otherwise the language of the
    existing conversation is kept, so transliterated or mixed-script messages
    do not flip the bot to English mid-dialogue.
    """
    cyrillic_count, latin_count = _script_counts(text)
    if cyrillic_count > latin_count:
        return "ru"
    return "ru" if history_has_cyrillic(user_id) else "en"
