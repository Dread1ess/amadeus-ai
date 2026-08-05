"""Telegram command and message handlers."""

import logging
import random
import time

try:
    from telegram import Update
    from telegram.ext import ContextTypes
except ImportError as e:
    raise ImportError(
        "Missing dependency: python-telegram-bot. Install it with `pip install python-telegram-bot`."
    ) from e

from ai import ask_ai
from config import (
    STICKER_COOLDOWN,
    STICKER_REPLY_COOLDOWN,
    STICKER_TEXT_REPLIES,
)
from language import resolve_language
from memory import add_to_history, clear_history
from persona import KURISU_SYSTEM_PROMPT
from stickers import (
    STICKER_REACTION_POOL,
    get_random_sticker,
    get_sticker_for_emoji,
    load_sticker_packs,
    pick_reaction,
    react_to_message,
    sticker_cooldown,
    sticker_reply_cooldown,
)

logger = logging.getLogger(__name__)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command and list the available commands."""
    help_text = (
        "🧠 **Amadeus — Makise Kurisu**\n\n"
        "What, can't you read? Fine, I'll explain for the specially gifted:\n\n"
        "**Commands:**\n"
        "/clear — Clear history (I'll just forget your nonsense)\n"
        "/help — You're reading it right now\n\n"
        "**Tip:** Just chat with me — I pick a working model automatically, "
        "you don't need to configure anything. "
        "I'm a neuroscientist, so ask smart questions!\n\n"
        "**Reactions & stickers:** I react to your messages when I feel like it, "
        "and sending me a sticker usually earns a reaction in return."
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
    quoted = update.message.reply_to_message
    if quoted:
        if quoted.text:
            context_message = (
                f"[Message from {user_name} replying to your earlier message "
                f'"{quoted.text[:200]}"]: {user_message}'
            )
        elif quoted.sticker:
            context_message = (
                f"[Message from {user_name} replying to one of your stickers]: {user_message}"
            )

    language = resolve_language(user_id, user_message)
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

    # An emotional reply also gets a fitting emoji reaction on the user's message.
    reaction_emoji = pick_reaction(sticker_emoji)
    if reaction_emoji:
        await react_to_message(update.message, reaction_emoji)


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """React to a sticker the user sent, in character and only when fitting.

    Every interaction is best-effort: any failure is logged and swallowed so a
    sticker can never trigger the global error handler.
    """
    try:
        message = update.message
        if message is None:
            return
        user_id = update.effective_user.id if update.effective_user else 0

        await load_sticker_packs(context.bot)

        # Rapid sticker spam gets only a cheap emoji reaction, nothing more.
        now = time.time()
        if now - sticker_reply_cooldown.get(user_id, 0) < STICKER_REPLY_COOLDOWN:
            await react_to_message(message, random.choice(STICKER_REACTION_POOL))
            return

        roll = random.random()
        if roll < 0.45:
            await react_to_message(message, random.choice(STICKER_REACTION_POOL))
        elif roll < 0.80:
            sticker_file_id = get_random_sticker()
            if sticker_file_id:
                await message.reply_sticker(sticker_file_id)
            else:
                await react_to_message(message, random.choice(STICKER_REACTION_POOL))
        else:
            language = resolve_language(user_id, "")
            await message.reply_text(random.choice(STICKER_TEXT_REPLIES[language]))
        sticker_reply_cooldown[user_id] = now
    except Exception as e:
        logger.exception("Failed to react to sticker: %s", e)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unexpected errors and notify the user with an in-character message."""
    logger.exception("Error while processing update: %s", context.error)
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "Hmm... Seems a critical error occurred. "
            "Don't even know what to say... Fine, write /help, "
            "maybe there's something understandable there."
        )
