"""Central configuration for the Amadeus bot.

Loads credentials from the environment (a local .env file is read automatically),
defines the model fallback chain, and holds every sticker/emoji/cooldown constant
used by the rest of the application.
"""

import logging
import os


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
]

# DeepSeek models served by the native DeepSeek API. The value is the model
# identifier expected by the DeepSeek endpoint, which differs from the key.
DEEPSEEK_MODELS = {
    "deepseek/deepseek-chat": "deepseek-chat",
}

# Per-attempt request timeout and how long a failing model is skipped.
MODEL_TIMEOUT = 25
MODEL_COOLDOWN_SECONDS = 60

# Kurisu sticker packs. Stickers are matched to a reply by their native emoji.
STICKER_PACKS = ["kurisu_II", "kurisu_I"]

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

# Telegram message reactions Kurisu may set. Only emojis from the regular
# (non-premium) reaction set are used so the API accepts them.
REACTION_FOR_EMOTION = {
    "😠": "😡", "😡": "😡", "😤": "😡",
    "😳": "😮", "🫣": "😮", "😯": "😮", "😮💨": "😮", "😵💫": "😮", "🥴": "😮",
    "🥱": "🥱", "😴": "🥱",
    "😊": ["🥰", "😍", "❤️"], "😃": ["🥰", "😍", "❤️"], "😄": ["🥰", "😍", "❤️"],
    "😎": ["🔥", "👍"], "😌": ["🥰", "❤️"], "🙂": ["👍", "❤️"], "🤗": ["🥰", "❤️"],
    "🙃": ["😁", "😮"], "👍": "👍", "👋": "👍", "👌": "👌",
    "🤔": "🤔", "🧐": "🤔",
    "😒": "😐", "😬": "😐", "🤕": "😐", "😦": "😐", "😐": "😐",
}

# Reaction emojis used when Kurisu reacts to a sticker the user sent.
STICKER_REACTION_POOL = ["😍", "🥰", "❤️", "👍", "😁", "👏"]

# Short in-character reactions to a user sticker. Kept local so reacting does
# not consume a model request; picked based on the conversation language.
STICKER_TEXT_REPLIES = {
    "ru": [
        "Fueh?! И что это за стикер такой?!",
        "Ты серьёзно думаешь, что этим можно меня впечатлить?",
        "Хм... Ладно, признаю, это было почти мило.",
        "Ну всё, я официально засчитала это как спам.",
        "Ишь чего выдумал... Но ладно, продолжай.",
    ],
    "en": [
        "Fueh?! And just what is that sticker supposed to be?!",
        "You seriously think that's how you impress me?",
        "Hmm... Fine, I'll admit, that was almost cute.",
        "Alright, I'm officially counting that as spam.",
        "Ha! What was that supposed to be... but fine, go on.",
    ],
}

# Minimum seconds between text/sticker replies to a user's sticker, so a flood
# of stickers only gets a cheap emoji reaction and never spams back.
STICKER_REPLY_COOLDOWN = 3

# Stickers follow the model's emotion tag, limited only by a short cooldown so
# they are not spammed on consecutive replies.
STICKER_COOLDOWN = 2

# Per-user conversation history length.
MAX_HISTORY = 30

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
