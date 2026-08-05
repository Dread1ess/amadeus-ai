# 🧠 Amadeus — Makise Kurisu AI Bot

A Telegram chat bot that brings **Makise Kurisu** (Amadeus) from *Steins;Gate* to life. Features natural conversation, automatic model failover, and sticker reactions matched to her mood.

## ✨ Features

- **Authentic Persona:** Lively tsundere banter, custom greetings, and in-character responses.
- **Automatic Model Failover:** No configuration needed — the bot picks a working model by itself. If one model hits a rate limit or error, it silently switches to the next, with DeepSeek (Chat V3 / R1) as the last resort.
- **Emotion-Based Stickers:** Contextual sticker reactions from the official Kurisu sticker packs (`kurisu_I` and `kurisu_II`), gated by emotion and cooldowns.
- **Language Aware:** Automatically replies in the language the user writes in (Russian or English).
- **Privacy & Security:** Zero hardcoded API keys; loads credentials cleanly via `.env` or environment variables.

## 🚀 Quick Start

### 1. Clone & Setup Environment

```bash
git clone https://github.com/Dread1ess/amadeus-ai.git
cd amadeus-ai
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Credentials

Copy `.env.example` to `.env` and fill in your tokens:

```bash
cp .env.example .env
```

Edit `.env`:

```txt
TELEGRAM_TOKEN=your_telegram_bot_token_from_botfather
OPENROUTER_API_KEY=your_openrouter_api_key

# Optional: enables the DeepSeek models (Chat V3 / R1)
DEEPSEEK_API_KEY=your_deepseek_api_key
```

### 3. Run the Bot

```bash
python main.py
```

## 📌 Bot Commands

- `/start` — Initialize/restart the Amadeus system
- `/clear` — Clear chat memory
- `/help` — Show help

That's it — just talk to the bot and it picks a working model automatically.

## 📜 License

MIT
