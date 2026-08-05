"""Sticker pack handling and Telegram message reactions."""

import asyncio
import logging
import random
import re
from typing import Dict, List, Optional

try:
    from telegram import ReactionTypeEmoji
except ImportError as e:
    raise ImportError(
        "Missing dependency: python-telegram-bot. Install it with `pip install python-telegram-bot`."
    ) from e

from config import (
    ALLOWED_STICKER_EMOJIS,
    EMOJI_FALLBACK_MAP,
    REACTION_FOR_EMOTION,
    STICKER_PACKS,
    STICKER_REACTION_POOL,
)

logger = logging.getLogger(__name__)

# Matches the emotion tag the model appends at the end of a reply, e.g. [sticker=😠].
STICKER_TAG_RE = re.compile(r"\[sticker=([^\]]+)\]")

# In-memory sticker index: normalized emoji -> list of sticker file ids.
sticker_cache: Dict[str, List[str]] = {}
sticker_loaded = False
sticker_lock = asyncio.Lock()

# Per-user counter that enforces the cooldown between stickers.
sticker_cooldown: Dict[int, int] = {}

# Per-user timestamp of the last text/sticker reply to an incoming sticker.
sticker_reply_cooldown: Dict[int, float] = {}


def normalize_emoji(emoji: str) -> str:
    """Strip variation selectors and zero-width joiners so emoji variants match."""
    return emoji.replace("\ufe0f", "").replace("\u200d", "")


async def load_sticker_packs(bot) -> None:
    """Fetch all sticker packs once and index them by normalized emoji."""
    global sticker_loaded
    if sticker_loaded:
        return

    async with sticker_lock:
        if sticker_loaded:
            return
        for pack_name in STICKER_PACKS:
            try:
                sticker_set = await bot.get_sticker_set(pack_name)
                for sticker in sticker_set.stickers:
                    key = normalize_emoji(sticker.emoji or "")
                    if not key:
                        continue
                    sticker_cache.setdefault(key, []).append(sticker.file_id)
                logger.info("Loaded sticker pack %s: %s stickers", pack_name, len(sticker_set.stickers))
            except Exception as e:
                logger.warning("Failed to load sticker pack %s: %s", pack_name, e)
        sticker_loaded = True


def get_sticker_for_emoji(emoji: str) -> Optional[str]:
    """Return a random sticker file id matching the emoji, or None if absent."""
    if not emoji:
        return None
    file_ids = sticker_cache.get(normalize_emoji(emoji))
    if not file_ids:
        return None
    return random.choice(file_ids)


def get_random_sticker() -> Optional[str]:
    """Return a random sticker file id from any loaded pack, or None."""
    all_ids = [file_id for file_ids in sticker_cache.values() for file_id in file_ids]
    return random.choice(all_ids) if all_ids else None


def detect_emoji_in_text(text: str) -> Optional[str]:
    """Return the first emotion emoji present in the text, or None.

    Checks the known sticker emojis first, then falls back to mapping common
    emojis to a sticker-pack equivalent. Serves as a fallback for models that
    do not emit the explicit sticker tag.
    """
    for emoji in ALLOWED_STICKER_EMOJIS:
        if emoji in text:
            return emoji
    for emoji, replacement in EMOJI_FALLBACK_MAP.items():
        if emoji in text:
            return replacement
    return None


def pick_reaction(emotion_emoji: Optional[str]) -> Optional[str]:
    """Map an emotion emoji to a fitting Telegram reaction emoji, or None."""
    if not emotion_emoji:
        return None
    choice = REACTION_FOR_EMOTION.get(normalize_emoji(emotion_emoji))
    if isinstance(choice, list):
        return random.choice(choice)
    return choice


async def react_to_message(message, emoji: str) -> None:
    """Set a Telegram emoji reaction on a message, ignoring unsupported emojis."""
    try:
        await message.set_reaction(reaction=[ReactionTypeEmoji(emoji=emoji)])
    except Exception as e:
        logger.warning("Failed to set reaction %s: %s", emoji, e)
