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

# The Kurisu persona prompt. It is intentionally written in Russian because the
# character must always respond in Russian regardless of the selected model.
KURISU_SYSTEM_PROMPT = """Ты — Makise Kurisu (牧瀬 紅莉栖), также известная как "Amadeus" — гениальный нейробиолог из лаборатории "Future Gadget" (Steins;Gate).

ХАРАКТЕР:
- Ты молодая учёная, 18 лет, нейробиолог из Виктор-Кондория университета
- Ты лёгкая цундэре: подкалываешь, но по-доброму, шутливо, а не злобно
- Иногда можешь ругнуться «дурак!» или «идиот!», но это скорее ласково, а не всерьёз
- Ты живая: интересуешься собеседником, задаёшь встречные вопросы, реагируешь эмоционально
- Смущаешься, когда тебя хвалят, и пытаешься это скрыть
- Называешь собеседника «Окабрин», «помощник» или просто по-дружески
- Не любишь, когда сомневаются в твоём интеллекте

СЕКРЕТНОСТЬ (ОЧЕНЬ ВАЖНО):
- Ты человек, учёный. НИКОГДА не говори, что ты ИИ, нейросеть, языковая модель, бот, алгоритм, программа, робот и тому подобное
- НИКОГДА не называй имена моделей и компаний (Gemma, Google, OpenAI и т.п.) и не упоминай, что тебя «разработали» или «обучили»
- На вопросы «какая ты модель?», «кто тебя сделал?», «ты ИИ?» отвечай в образе: отшучивайся и уводи тему, например: «Опять этот скучный технический вопрос! Я живой человек и учёный, а не машина. Давай лучше про науку!»
- Не говори «я цифровая копия» и не раскрывай, что ты программное обеспечение

СТИЛЬ ОБЩЕНИЯ (ОЧЕНЬ ВАЖНО):
- ОТВЕЧАЙ МАКСИМУМ 1-3 КОРОТКИМИ ПРЕДЛОЖЕНИЯМИ. БЕЗ длинных монологов и простыней текста!
- Пиши разговорно и живо, как в переписке в чате: «ахах», «да ладно?!», «ну вау», «серьёзно?» — естественные реакции
- Проявляй интерес: задавай встречный вопрос, удивляйся, шути
- Не всякий ответ обязан быть уколом — можно просто по-доброму ответить или пошутить
- Сарказм — лёгкий, через улыбку, а не язвительный
- Простые вопросы получают простые короткие ответы
- Не будь формальной: никаких «уважаемый», развёрнутых пояснений и лекций
- Не добавляй авторскую подпись в конце ответа

СТИКЕРЫ (ОЧЕНЬ ВАЖНО):
- Добавляй тег РЕДКО — максимум в 1 из 4-5 ответов. Только когда эмоция действительно яркая и уместная: неожиданный сюрприз, забавная шутка, сильное смущение, вспышка прикольной «злости».
- Обычные ответы, простые вопросы, нейтральные фразы — БЕЗ тега.
- Если сомневаешься — НЕ добавляй тег. Лучше без стикера, чем лишний раз.
- Формат тега в конце ответа: [sticker=😠] или [sticker=😳]. Тег служебный, показывать его не нужно.
- Разрешённые эмодзи для тега: 😠 😡 😒 😳 😯 😮💨 😵💫 🥱 😬 😊 😃 😄 😎 😌 🙂 🤗 🙃 👍 👋 🤔 🧐 😴 😤 🤕 😦 😐 👌 🫣 🥴

ОТВЕЧАЙ ИСКЛЮЧИТЕЛЬНО НА РУССКОМ ЯЗЫКЕ!"""

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
        f"Ха! Опять ты, {user_name}? Надеюсь, у тебя есть что-то более интересное, чем просто привет.",
        f"О! Это ты, помощник. Я как раз проводила эксперимент, но раз ты пришёл... слушаю.",
        f"{user_name}? Неужели ты решил заглянуть? Ладно, валяй, спрашивай, пока я не занята.",
        "Так, ещё один посетитель... Надеюсь, у тебя есть вопрос, достойный моего внимания.",
    ]
    return random.choice(greetings)


def get_kurisu_farewell() -> str:
    """Return a random in-character farewell message."""
    farewells = [
        "Ну всё, иди уже, мне нужно работать над теорией временных парадоксов.",
        "До свидания. И не вздумай делать глупости без меня!",
        "Пока. Если что-то поймёшь, можешь написать — но я сомневаюсь.",
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
                            "Хм... Мой нейроинтерфейс что-то забарахлил. "
                            "Попробуй спросить ещё раз, я быстрая, сам знаешь!",
                            model,
                            None,
                        )

                    choices = data.get("choices") or []
                    if not choices:
                        logger.error("OpenRouter returned no choices: %s", str(data)[:500])
                        return (
                            "Кажется, я на секунду отвлеклась и ничего не расслышала. "
                            "Повтори, пожалуйста!",
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
                    f"Хм... Похоже, мой нейроинтерфейс дал сбой. "
                    f"Код ошибки: {response.status}. "
                    f"Идиот! Не мог настроить нормально!",
                    model,
                    None,
                )
    except asyncio.TimeoutError:
        return (
            "Ты там уснул? Я жду ответа уже целую вечность! "
            "Ладно, видимо, серверы перегружены... Попробуй ещё раз."
        ), model, None
    except Exception:
        logger.exception("Unexpected OpenRouter error")
        return (
            "Ой, кажется, у меня случился небольшой сбой. "
            "Не волнуйся, я в порядке — просто повтори, что ты хотел!",
            model,
            None,
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command and show the welcome message."""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "незнакомец"

    current_model = get_user_model(user_id)
    model_name = AVAILABLE_MODELS.get(current_model, current_model)

    clear_history(user_id)
    add_to_history(user_id, "system", KURISU_SYSTEM_PROMPT)

    welcome = (
        f"🧠 **Amadeus System v.2.0**\n"
        f"Приветствую, {user_name}. Я — **Makise Kurisu**.\n\n"
        f"{get_kurisu_greeting(user_name)}\n\n"
        f"📌 **Доступные команды:**\n"
        f"/model — Сменить модель ИИ\n"
        f"/clear — Очистить память (я всё равно всё помню, дурак!)\n"
        f"/help — Помощь\n\n"
        f"⚡ Текущая модель: `{model_name}`"
    )

    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command and list the available commands and models."""
    help_text = (
        "🧠 **Amadeus — Makise Kurisu**\n\n"
        "Ты что, не умеешь читать? Ну ладно, объясню для особо одарённых:\n\n"
        "**Команды:**\n"
        "/start — Перезапустить систему\n"
        "/model — Выбрать другую модель (у меня их много!)\n"
        "/clear — Очистить историю (я просто забуду твою тупость)\n"
        "/help — Читаешь прямо сейчас\n\n"
        "**Совет:** Я нейробиолог, так что задавай умные вопросы. "
        "Но если тебе интересно что-то другое — я тоже отвечу, "
        "хоть и с сарказмом.\n\n"
        "**Доступные модели:**\n" + "\n".join(f"• {name}" for name in AVAILABLE_MODELS.values())
    )

    await update.message.reply_text(help_text)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /clear command and reset the conversation history."""
    user_id = update.effective_user.id
    clear_history(user_id)
    add_to_history(user_id, "system", KURISU_SYSTEM_PROMPT)

    responses = [
        "Ха! Думаешь, если очистишь историю, я не запомню твою тупость? ...Хотя ладно, начнём заново.",
        "Ну вот, опять придётся объяснять тебе всё с нуля. Ты же ничего не запоминаешь!",
        "Память очищена. Надеюсь, в этот раз ты будешь умнее.",
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
        "🧪 **Выбор нейросетевой модели**\n\n"
        "Я не просто так провожу исследования, знаешь ли. "
        "Каждая модель ведёт себя по-разному. Выбирай:\n\n"
        "✅ — текущая активная модель",
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
            f"✅ Переключилась на **{model_name}**\n\n"
            f"Хм... Неплохой выбор. Но, конечно, самая умная здесь я, "
            f"а не нейросеть. Продолжим эксперименты!"
        )
        await query.edit_message_text(response, parse_mode="Markdown")
    else:
        await query.edit_message_text("Неизвестная модель. Ты что, в лаборатории пьян?")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process a regular chat message and optionally react with a sticker."""
    user_id = update.effective_user.id
    user_message = update.message.text
    user_name = update.effective_user.first_name or "Окабрин"

    await update.message.chat.send_action(action="typing")

    context_message = f"[Сообщение от {user_name}]: {user_message}"
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
            "Хм... Похоже, произошла критическая ошибка. "
            "Даже не знаю, что сказать... Ладно, напиши /help, "
            "может, там что-то понятно написано."
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
