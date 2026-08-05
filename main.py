"""Amadeus (Kurisu) Telegram bot entry point.

Wires up the application, registers handlers, and starts polling. The actual
logic lives in the sibling modules (handlers, ai, stickers, language, ...).
"""

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters
except ImportError as e:
    raise ImportError(
        "Missing dependency: python-telegram-bot. Install it with `pip install python-telegram-bot`."
    ) from e

from config import OPENROUTER_API_KEY, TELEGRAM_TOKEN
from handlers import (
    clear_command,
    error_handler,
    handle_message,
    handle_sticker,
    help_command,
    start,
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
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    application.add_error_handler(error_handler)

    print("Amadeus (Kurisu) is running. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
