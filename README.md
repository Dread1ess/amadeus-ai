# 🧠 Amadeus — Makise Kurisu AI Bot

A Telegram chat bot powered by OpenRouter that brings **Makise Kurisu** (Amadeus) from *Steins;Gate* to life. Features natural conversation, multi-model support, and automatic sticker reactions matched to her mood.

## ✨ Features

- **Authentic Persona:** Lively tsundere banter, custom greetings, and in-character responses.
- **Emotion-Based Stickers:** Contextual sticker reactions from the official Kurisu sticker packs (`kurisu_I` and `kurisu_II`), gated by emotion and cooldowns.
- **Multi-Model Support:** Switch between various LLMs on the fly using `/model`.
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
```env
TELEGRAM_TOKEN=your_telegram_bot_token_from_botfather
OPENROUTER_API_KEY=your_openrouter_api_key
```

### 3. Run the Bot

```bash
python main.py
```

## 📌 Bot Commands

- `/start` — Initialize/restart the Amadeus system
- `/model` — Select an AI model from the menu
- `/clear` — Clear chat memory
- `/help` — Show available commands and models

## 📜 License

MIT
