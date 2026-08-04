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
from typing import Dict, List, Optional, Tuple

try:
    import aiohttp
except ImportError as e:
    raise ImportError("Missing dependency: aiohttp. Install it with `pip install aiohttp`.") from e

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        CallbackQueryHandler,
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

# Mapping of model identifiers to friendly display names. All models are free.
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
}

# Kurisu sticker packs. Stickers are matched to a reply by their native emoji.
STICKER_PACKS = ["kurisu_II", "kurisu_I"]

# Matches the emotion tag the model appends at the end of a reply, e.g. [sticker=😠].
STICKER_TAG_RE = re.compile(r"\[sticker=([^\]]+)\]")

# Stickers are never sent on every reply. These settings limit how often they
# appear even when the model marks a reply as emotional.
STICKER_CHANCE = 0.5
STICKER_COOLDOWN = 3

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
- Normal replies, simple questions, neutral phrases — WITHOUT a tag.
- If in doubt — DON'T add a tag. Better no sticker than an extra one.
- Tag format at the end of reply: [sticker=😠] or [sticker=😳]. The tag is internal, don't show it.
- Allowed emojis for the tag: 😠 😡 😒 😳 😯 😮💨 😵💫 🥱 😬 😊 😃 😄 😎 😌 🙂 🤗 🙃 👍 👋 🤔 🧐 😴 😤 🤕 😦 😐 👌 🫣 🥴

REPLY EXCLUSIVELY IN ENGLISH!"""

# Per-user conversation history and selected model.
user_sessions: Dict[int, List[Dict[str, str]]] = {}
user_models: Dict[int, str] = {}
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


def get_user_model(user_id: int) -> str:
    """Return the model selected by the user, defaulting to Gemma 4 26B."""
    if user_id not in user_models:
        user_models[user_id] = "google/gemma-4-26b-a4b-it:free"
    return user_models[user_id]


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


async def ask_openrouter(
    user_id: int, message: str, model: str = None
) -> Tuple[str, str, Optional[str]]:
    """Send a request to OpenRouter with the Kurisu prompt.

    Returns a tuple of the reply text, the model actually used, and an emoji for
    a matching sticker (or None when the reply carries no strong emotion).
    """
    if model is None:
        model = get_user_model(user_id)

    add_to_history(user_id, "user", message)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/kurisu_bot",
        "X-Title": "Amadeus - Kurisu AI",
    }

    messages = get_user_history(user_id).copy()
    messages.insert(0, {"role": "system", "content": KURISU_SYSTEM_PROMPT})

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 220,
        "temperature": 0.9,
        "top_p": 0.9,
        "frequency_penalty": 0.3,
        "presence_penalty": 0.3,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                OPENROUTER_URL, headers=headers, json=payload, timeout=90
            ) as response:
                if response.status == 200:
                    data = await response.json()

                    if data.get("error"):
                        logger.error("OpenRouter API error: %s", data["error"])
                        return (
                            "Hmm... My neural interface glitched. "
                            "Try asking again, I'm quick, you know!",
                            model,
                            None,
                        )

                    choices = data.get("choices") or []
                    if not choices:
                        logger.error("OpenRouter returned no choices: %s", str(data)[:500])
                        return (
                            "Seems I spaced out for a second and didn't catch that. "
                            "Could you repeat that, please?",
                            model,
                            None,
                        )

                    bot_reply = choices[0]["message"]["content"]
                    used_model = data.get("model", model)

                    sticker_emoji = None
                    tag_match = STICKER_TAG_RE.search(bot_reply)
                    if tag_match:
                        sticker_emoji = tag_match.group(1).strip()
                        bot_reply = STICKER_TAG_RE.sub("", bot_reply).strip()

                    add_to_history(user_id, "assistant", bot_reply)
                    return bot_reply, used_model, sticker_emoji

                error_text = await response.text()
                logger.error("OpenRouter error %s: %s", response.status, error_text[:500])
                return (
                    f"Hmm... Looks like my neural interface crashed. "
                    f"Error code: {response.status}. "
                    f"Idiot! Couldn't set it up properly!",
                    model,
                    None,
                )
    except asyncio.TimeoutError:
        return (
            "You fall asleep there? I've been waiting forever! "
            "Fine, guess the servers are overloaded... Try again.",
        ), model, None
    except Exception:
        logger.exception("Unexpected OpenRouter error")
        return (
            "Oops, looks like I had a little glitch. "
            "Don't worry, I'm fine — just repeat what you wanted!",
        ), model, None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command and show the welcome message."""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "stranger"

    current_model = get_user_model(user_id)
    model_name = AVAILABLE_MODELS.get(current_model, current_model)

    clear_history(user_id)
    add_to_history(user_id, "system", KURISU_SYSTEM_PROMPT)

    welcome = (
        f"🧠 **Amadeus System v.2.0**\n"
        f"Welcome, {user_name}. I'm **Makise Kurisu**.\n\n"
        f"{get_kurisu_greeting(user_name)}\n\n"
        f"📌 **Available commands:**\n"
        f"/model — Switch AI model\n"
        f"/clear — Clear memory (I'll remember your stupidity anyway!)\n"
        f"/help — Help\n\n"
        f"⚡ Current model: `{model_name}`"
    )

    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command and list the available commands and models."""
    help_text = (
        "🧠 **Amadeus — Makise Kurisu**\n\n"
        "What, can't you read? Fine, I'll explain for the specially gifted:\n\n"
        "**Commands:**\n"
        "/start — Restart the system\n"
        "/model — Pick another model (I've got plenty!)\n"
        "/clear — Clear history (I'll just forget your nonsense)\n"
        "/help — You're reading it right now\n\n"
        "**Tip:** I'm a neuroscientist, so ask smart questions. "
        "But if you're curious about something else — I'll answer that too, "
        "though with sarcasm.\n\n"
        "**Available models:**\n" + "\n".join(f"• {name}" for name in AVAILABLE_MODELS.values())
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


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /model command and show the inline model picker."""
    keyboard = []
    current_model = get_user_model(update.effective_user.id)

    for model_id, model_name in AVAILABLE_MODELS.items():
        label = f"✅ {model_name}" if model_id == current_model else model_name
        keyboard.append([InlineKeyboardButton(label, callback_data=f"model_{model_id}")])

    await update.message.reply_text(
        "🧪 **Neural Network Model Selection**\n\n"
        "I don't conduct research for nothing, you know. "
        "Each model behaves differently. Choose:\n\n"
        "✅ — currently active model",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def model_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle taps on the model picker buttons."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    model_id = query.data.replace("model_", "")

    if model_id in AVAILABLE_MODELS:
        user_models[user_id] = model_id
        model_name = AVAILABLE_MODELS[model_id]

        response = (
            f"✅ Switched to **{model_name}**\n\n"
            f"Hmm... Not a bad choice. But of course, the smartest one here is me, "
            f"not the neural network. Let's continue the experiments!"
        )
        await query.edit_message_text(response, parse_mode="Markdown")
    else:
        await query.edit_message_text("Unknown model. What, are you drunk in the lab?")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process a regular chat message and optionally react with a sticker."""
    user_id = update.effective_user.id
    user_message = update.message.text
    user_name = update.effective_user.first_name or "Okabe"

    await update.message.chat.send_action(action="typing")

    context_message = f"[Message from {user_name}]: {user_message}"
    bot_reply, used_model, sticker_emoji = await ask_openrouter(user_id, context_message)

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

    if sticker_emoji and sticker_cooldown.get(user_id, 0) <= 0 and random.random() < STICKER_CHANCE:
        try:
            await load_sticker_packs(context.bot)
            sticker_file_id = get_sticker_for_emoji(sticker_emoji)
            if sticker_file_id:
                await update.message.reply_sticker(sticker_file_id)
                sticker_cooldown[user_id] = STICKER_COOLDOWN
            else:
                logger.info("No sticker found for emoji: %s", sticker_emoji)
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
    application.add_handler(CommandHandler("model", model_command))
    application.add_handler(CallbackQueryHandler(model_callback, pattern="^model_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    print("Amadeus (Kurisu) is running. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()