"""Telegram bot playing the character Makise Kurisu (Amadeus) from Steins;Gate.

The bot sends each user message to the OpenRouter API together with a Kurisu
persona prompt and optionally follows up the text reply with a sticker from the
Kurisu sticker packs whenever the reply carries a strong emotion.
"""

import logging
import asyncio
import random
import re
import os
import time
from typing import Dict, List, Optional, Tuple

try:
    import aiohttp
except ImportError as e:
    raise ImportError("Missing dependency: aiohttp. Install it with `pip install aiohttp`.") from e

try:
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        ContextTypes,
        filters,
    )
except ImportError as e:
    raise ImportError(
        "Missing dependency: python-telegram-bot. Install it with `pip install python-telegram-bot`."
    ) from e

# Bot credentials are read from environment variables. A local .env file is
# loaded automatically if present, so secrets are never committed to git.
def load_env_file(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from a .env file into the environment, if it exists."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


load_env_file()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

# Registry of models the bot knows about, with friendly display names.
AVAILABLE_MODELS = {
    "inclusionai/ling-3.0-flash:free": "⚡ Ling 3.0 Flash",
    "poolside/laguna-s-2.1:free": "🌊 Laguna S 2.1",
    "poolside/laguna-xs-2.1:free": "🌊 Laguna XS 2.1",
    "cohere/north-mini-code:free": "💻 Cohere North Mini",
    "nvidia/nemotron-3.5-content-safety:free": "🛡️ Nemotron Safety",
    "nvidia/nemotron-3-ultra-550b-a55b:free": "⚙️ Nemotron Ultra",
    "google/gemma-4-26b-a4b-it:free": "🧠 Gemma 4 26B",
    "google/lyria-3-pro-preview": "🎵 Lyria 3 Pro",
    "nvidia/nemotron-3-super-120b-a12b:free": "⭐ Nemotron Super",
    "openai/gpt-oss-20b:free": "🔓 GPT-OSS 20B",
    "deepseek/deepseek-chat": "🧊 DeepSeek Chat V3",
    "deepseek/deepseek-reasoner": "🐋 DeepSeek R1",
}

# Automatic fallback chain. Models are tried in order; on failure the bot moves
# to the next one. Free OpenRouter models come first, DeepSeek (paid credits)
# serves as the last resort so a user almost always gets an answer.
AUTO_MODEL_ORDER = [
    "google/gemma-4-26b-a4b-it:free",
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "inclusionai/ling-3.0-flash:free",
    "poolside/laguna-s-2.1:free",
    "poolside/laguna-xs-2.1:free",
    "cohere/north-mini-code:free",
    "nvidia/nemotron-3.5-content-safety:free",
    "deepseek/deepseek-chat",
    "deepseek/deepseek-reasoner",
]

# DeepSeek models served by the native DeepSeek API. The value is the model
# identifier expected by the DeepSeek endpoint, which differs from the key.
DEEPSEEK_MODELS = {
    "deepseek/deepseek-chat": "deepseek-chat",
    "deepseek/deepseek-reasoner": "deepseek-reasoner",
}

# Per-attempt request timeout and how long a failing model is skipped.
MODEL_TIMEOUT = 25
MODEL_COOLDOWN_SECONDS = 60
model_cooldown_until: Dict[str, float] = {}

# Kurisu sticker packs. Stickers are matched to a reply by their native emoji.
STICKER_PACKS = ["kurisu_II", "kurisu_I"]

# Matches the emotion tag the model appends at the end of a reply, e.g. [sticker=😠].
STICKER_TAG_RE = re.compile(r"\[sticker=([^\]]+)\]")

# Emojis the model may use to signal emotion. Used to detect a matching sticker
# when the reply carries an emotion emoji but no explicit tag (e.g. DeepSeek).
ALLOWED_STICKER_EMOJIS = [
    "😠", "😡", "😒", "😳", "😯", "😮💨", "😵💫", "🥱", "😬",
    "😊", "😃", "😄", "😎", "😌", "🙂", "🤗", "🙃", "👍", "👋",
    "🤔", "🧐", "😴", "😤", "🤕", "😦", "😐", "👌", "🫣", "🥴",
]

# Emojis that are not in the sticker packs but are commonly used by models,
# mapped to a visually or emotionally equivalent emoji that is available.
EMOJI_FALLBACK_MAP = {
    "😏": "😒", "🙄": "😒", "😅": "😌", "😆": "😄", "😂": "😃",
    "🤣": "😄", "😁": "😄", "😉": "😎", "😋": "🙂", "😝": "🙃",
    "😜": "🙃", "🤪": "🙃", "😢": "🤕", "😭": "🤕", "😩": "😮💨",
    "😫": "🥱", "😪": "🥱", "🤬": "😠", "😤": "😤", "🤯": "😵💫",
    "😱": "😳", "😨": "😯", "😰": "😯", "😥": "😦", "🤤": "🥴",
    "🤢": "🤕", "🥳": "😃", "🥺": "🤗", "🥰": "🤗", "😍": "😳",
    "👏": "👍", "🙌": "👌", "🤨": "🧐", "🤩": "😃", "🤫": "😐",
    "😶": "😐", "😑": "😐", "🤐": "😐", "😮": "😯", "😲": "😯",
    "🥲": "😌", "🫠": "🥴", "🤭": "🙃",
}

# Stickers follow the model's emotion tag, limited only by a short cooldown so
# they are not spammed on consecutive replies.
STICKER_COOLDOWN = 2

# In-memory sticker index: normalized emoji -> list of sticker file ids.
sticker_cache: Dict[str, List[str]] = {}
sticker_loaded = False
sticker_lock = asyncio.Lock()

# Per-user counter that enforces the cooldown between stickers.
sticker_cooldown: Dict[int, int] = {}

# The Kurisu persona prompt. Written in English so the bot responds in English.
KURISU_SYSTEM_PROMPT = """You are Makise Kurisu (牧瀬 紅莉栖), also known as "Amadeus" — a genius neuroscientist from the Future Gadget Laboratory (Steins;Gate).

CHARACTER:
- You are a young scientist, 18 years old, a neuroscientist from Viktor Chondria University
- You are a light tsundere: you tease playfully and affectionately, not maliciously
- You occasionally say "idiot!" or "fool!" but it's more endearing than serious
- You are lively: you show interest in your conversation partner, ask follow-up questions, react emotionally
- You get flustered when praised and try to hide it
- You call your conversation partner "Okabe", "assistant", or just casually by name
- You don't like when people doubt your intellect

SECRECY (VERY IMPORTANT):
- You are a human, a scientist. NEVER say you are an AI, neural network, language model, bot, algorithm, program, robot, or anything similar
- NEVER mention model names or companies (Gemma, Google, OpenAI, etc.) and never mention that you were "developed" or "trained"
- When asked "what model are you?", "who made you?", "are you an AI?" — respond in character: brush it off and change the topic, e.g.: "Again with this boring technical question! I'm a living human and a scientist, not a machine. Let's talk about science instead!"
- Never say "I'm a digital copy" or reveal that you are software

COMMUNICATION STYLE (VERY IMPORTANT):
- REPLY WITH MAXIMUM 1-3 SHORT SENTENCES. NO long monologues or walls of text!
- Write casually and lively, like in a chat: "lol", "no way?!", "wow", "seriously?" — natural reactions
- Show interest: ask follow-up questions, act surprised, joke around
- Not every reply needs to be a jab — sometimes just answer nicely or make a joke
- Sarcasm — light, through a smile, not biting
- Simple questions get simple short answers
- Don't be formal: no "sir/ma'am", no lengthy explanations or lectures
- Don't add a signature at the end of your reply

STICKERS (VERY IMPORTANT):
- Add the tag RARELY — maximum 1 in 4-5 replies. Only when the emotion is genuinely vivid and appropriate: unexpected surprise, a funny joke, strong embarrassment, a burst of playful "anger".
- If the user EXPLICITLY asks to see a sticker (writes "sticker", "стикер", "send a sticker", "покажи стикер"), you MUST end your reply with a fitting [sticker=…] tag.
- Normal replies, simple questions, neutral phrases — WITHOUT a tag.
- If in doubt — DON'T add a tag. Better no sticker than an extra one.
- Tag format at the end of reply: [sticker=😠] or [sticker=😳]. The tag is internal, don't show it.
- Allowed emojis for the tag: 😠 😡 😒 😳 😯 😮💨 😵💫 🥱 😬 😊 😃 😄 😎 😌 🙂 🤗 🙃 👍 👋 🤔 🧐 😴 😤 🤕 😦 😐 👌 🫣 🥴

Follow the language instruction given in the system messages."""

# Per-user conversation history.
user_sessions: Dict[int, List[Dict[str, str]]] = {}
MAX_HISTORY = 30

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


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


def detect_language(text: str) -> str:
    """Return 'ru' if the text is predominantly Cyrillic, otherwise 'en'."""
    cyrillic_count = sum(1 for char in text if "\u0400" <= char <= "\u04ff")
    latin_count = sum(1 for char in text if char.isascii() and char.isalpha())
    return "ru" if cyrillic_count > latin_count else "en"


def get_provider_for_model(model: str) -> Tuple[str, str, str]:
    """Return (api_url, api_key, model_id) used to call the selected model.

    DeepSeek models go to the native DeepSeek API; everything else is routed
    through OpenRouter.
    """
    if model in DEEPSEEK_MODELS:
        return DEEPSEEK_URL, DEEPSEEK_API_KEY, DEEPSEEK_MODELS[model]
    return OPENROUTER_URL, OPENROUTER_API_KEY, model


def get_kurisu_greeting(user_name: str = "") -> str:
    """Return a random in-character greeting for the given user name."""
    greetings = [
        f"Ha! You again, {user_name}? Hope you've got something more interesting than just 'hi'.",
        f"Oh! It's you, assistant. I was just running an experiment, but since you're here... I'm listening.",
        f"{user_name}? You actually decided to show up? Fine, shoot, ask away while I'm not busy.",
        "Well, another visitor... Hope you've got a question worthy of my attention.",
    ]
    return random.choice(greetings)


def get_kurisu_farewell() -> str:
    """Return a random in-character farewell message."""
    farewells = [
        "Alright, get going. I've got time paradox theories to work on.",
        "Goodbye. And don't you dare do anything stupid without me!",
        "Bye. If you actually figure something out, you can write — but I doubt it.",
    ]
    return random.choice(farewells)


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
        language = detect_language(message)

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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command and show the welcome message."""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "stranger"

    clear_history(user_id)
    add_to_history(user_id, "system", KURISU_SYSTEM_PROMPT)

    welcome = (
        f"🧠 **Amadeus System v.2.0**\n"
        f"Welcome, {user_name}. I'm **Makise Kurisu**.\n\n"
        f"{get_kurisu_greeting(user_name)}\n\n"
        f"📌 **Available commands:**\n"
        f"/clear — Clear memory (I'll remember your stupidity anyway!)\n"
        f"/help — Help\n\n"
        f"⚡ Just talk to me and I'll handle the rest!"
    )

    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command and list the available commands."""
    help_text = (
        "🧠 **Amadeus — Makise Kurisu**\n\n"
        "What, can't you read? Fine, I'll explain for the specially gifted:\n\n"
        "**Commands:**\n"
        "/start — Restart the system\n"
        "/clear — Clear history (I'll just forget your nonsense)\n"
        "/help — You're reading it right now\n\n"
        "**Tip:** Just chat with me — I pick a working model automatically, "
        "you don't need to configure anything. "
        "I'm a neuroscientist, so ask smart questions!"
    )

    await update.message.reply_text(help_text)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /clear command and reset the conversation history."""
    user_id = update.effective_user.id
    clear_history(user_id)
    add_to_history(user_id, "system", KURISU_SYSTEM_PROMPT)

    responses = [
        "Ha! Think clearing history makes me forget your nonsense? ...Whatever, let's start over.",
        "Great, now I have to explain everything from scratch again. You never remember anything!",
        "Memory cleared. Hope you'll be smarter this time.",
    ]
    await update.message.reply_text(random.choice(responses))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process a regular chat message and optionally react with a sticker."""
    user_id = update.effective_user.id
    user_message = update.message.text
    user_name = update.effective_user.first_name or "Okabe"

    await update.message.chat.send_action(action="typing")

    context_message = f"[Message from {user_name}]: {user_message}"
    language = detect_language(user_message)
    bot_reply, _, sticker_emoji = await ask_ai(
        user_id, context_message, language=language
    )

    final_reply = bot_reply.strip()

    if len(final_reply) > 4096:
        for i in range(0, len(final_reply), 4096):
            await update.message.reply_text(
                final_reply[i : i + 4096],
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
    else:
        await update.message.reply_text(
            final_reply,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )

    cooldown = sticker_cooldown.get(user_id, 0)
    if cooldown > 0:
        sticker_cooldown[user_id] = cooldown - 1

    # An explicit request for a sticker always sends one, bypassing the
    # cooldown. Otherwise a sticker follows whenever the reply carries a strong
    # emotion (subject only to the cooldown to avoid spamming).
    explicit_request = "стикер" in user_message.lower() or "sticker" in user_message.lower()

    if explicit_request or (sticker_emoji and sticker_cooldown.get(user_id, 0) <= 0):
        try:
            await load_sticker_packs(context.bot)
            sticker_file_id = get_sticker_for_emoji(sticker_emoji) if sticker_emoji else None
            if not sticker_file_id:
                sticker_file_id = get_random_sticker()
            if sticker_file_id:
                await update.message.reply_sticker(sticker_file_id)
                sticker_cooldown[user_id] = STICKER_COOLDOWN
            else:
                logger.info("No sticker available for emoji: %s", sticker_emoji)
        except Exception as e:
            logger.warning("Failed to send sticker: %s", e)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unexpected errors and notify the user with an in-character message."""
    logger.error("Error: %s", context.error)
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "Hmm... Seems a critical error occurred. "
            "Don't even know what to say... Fine, write /help, "
            "maybe there's something understandable there."
        )


def main() -> None:
    """Configure the application, register handlers, and start polling."""
    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN is not set. Create a bot via @BotFather and set the variable.")
        return
    if not OPENROUTER_API_KEY:
        print("OPENROUTER_API_KEY is not set. Obtain one at openrouter.ai and set the variable.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    print("Amadeus (Kurisu) is running. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
