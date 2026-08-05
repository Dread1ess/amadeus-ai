"""AI providers, the automatic fallback chain, and reply generation."""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple

try:
    import aiohttp
except ImportError as e:
    raise ImportError("Missing dependency: aiohttp. Install it with `pip install aiohttp`.") from e

from config import (
    AUTO_MODEL_ORDER,
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODELS,
    DEEPSEEK_URL,
    MODEL_COOLDOWN_SECONDS,
    MODEL_TIMEOUT,
    OPENROUTER_API_KEY,
    OPENROUTER_URL,
)
from language import resolve_language
from memory import add_to_history, get_user_history
from persona import KURISU_SYSTEM_PROMPT
from stickers import STICKER_TAG_RE, detect_emoji_in_text

logger = logging.getLogger(__name__)

# How long a failing model is skipped after an error.
model_cooldown_until: Dict[str, float] = {}


def get_provider_for_model(model: str) -> Tuple[str, str, str]:
    """Return (api_url, api_key, model_id) used to call the selected model.

    DeepSeek models go to the native DeepSeek API; everything else is routed
    through OpenRouter.
    """
    if model in DEEPSEEK_MODELS:
        return DEEPSEEK_URL, DEEPSEEK_API_KEY, DEEPSEEK_MODELS[model]
    return OPENROUTER_URL, OPENROUTER_API_KEY, model


async def call_model(
    api_url: str, api_key: str, api_model: str, messages: List[Dict[str, str]], model_key: str
) -> Optional[str]:
    """Call a single AI provider and return the reply text, or None on failure.

    Retryable failures (rate limits, 5xx, timeouts, malformed responses) put the
    model on a short cooldown so the fallback loop does not hammer it.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/kurisu_bot",
        "X-Title": "Amadeus - Kurisu AI",
    }

    # DeepSeek's reasoning model does not support these sampling parameters.
    payload = {
        "model": api_model,
        "messages": messages,
        "max_tokens": 220,
    }
    if api_model != "deepseek-reasoner":
        payload.update({
            "temperature": 0.9,
            "top_p": 0.9,
            "frequency_penalty": 0.3,
            "presence_penalty": 0.3,
        })

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                api_url, headers=headers, json=payload, timeout=MODEL_TIMEOUT
            ) as response:
                if response.status == 200:
                    data = await response.json()

                    if data.get("error"):
                        logger.warning("AI API error for %s: %s", model_key, data["error"])
                        return None

                    choices = data.get("choices") or []
                    if not choices:
                        logger.warning("AI API returned no choices for %s: %s", model_key, str(data)[:500])
                        return None

                    return choices[0]["message"]["content"]

                error_text = await response.text()
                logger.warning("AI API error %s for %s: %s", response.status, model_key, error_text[:300])
                if response.status == 429 or response.status >= 500:
                    model_cooldown_until[model_key] = time.time() + MODEL_COOLDOWN_SECONDS
                return None
    except asyncio.TimeoutError:
        logger.warning("AI API timeout for %s", model_key)
        model_cooldown_until[model_key] = time.time() + MODEL_COOLDOWN_SECONDS
        return None
    except Exception:
        logger.exception("Unexpected AI API error for %s", model_key)
        model_cooldown_until[model_key] = time.time() + MODEL_COOLDOWN_SECONDS
        return None


def all_models_failed_message(language: str) -> str:
    """Return a friendly in-character message when every model is unavailable."""
    return (
        "Кажется, все мои мозги сейчас перегружены. Попробуй через минуту, ладно?"
        if language == "ru"
        else "Seems all my brains are overloaded right now. Try again in a minute, okay?"
    )


async def ask_ai(
    user_id: int, message: str, language: str = None
) -> Tuple[str, str, Optional[str]]:
    """Ask the Kurisu prompt to an AI provider, failing over across models.

    Returns a tuple of the reply text, the model that produced it, and an emoji
    for a matching sticker (or None). Errors and rate limits are handled
    silently by trying the next model in the chain.
    """
    add_to_history(user_id, "user", message)

    if language is None:
        language = resolve_language(user_id, message)

    messages = get_user_history(user_id).copy()
    messages.insert(0, {"role": "system", "content": KURISU_SYSTEM_PROMPT})

    language_instruction = {
        "ru": "Пользователь пишет на русском. Отвечай на русском языке.",
        "en": "The user is writing in English. Reply in English.",
    }[language]
    messages.insert(1, {"role": "system", "content": language_instruction})

    for candidate in AUTO_MODEL_ORDER:
        if model_cooldown_until.get(candidate, 0) > time.time():
            continue

        api_url, api_key, api_model = get_provider_for_model(candidate)
        if not api_key:
            continue

        content = await call_model(api_url, api_key, api_model, messages, candidate)
        if content is None:
            continue

        bot_reply = content
        sticker_emoji = None
        tag_match = STICKER_TAG_RE.search(bot_reply)
        if tag_match:
            sticker_emoji = tag_match.group(1).strip()
            bot_reply = STICKER_TAG_RE.sub("", bot_reply).strip()
        else:
            sticker_emoji = detect_emoji_in_text(bot_reply)

        add_to_history(user_id, "assistant", bot_reply)
        return bot_reply, candidate, sticker_emoji

    logger.error("All models failed for user %s", user_id)
    return all_models_failed_message(language), AUTO_MODEL_ORDER[0], None
