"""Kurisu's persona: the system prompt and in-character greeting lines."""

import random
from pathlib import Path

# The persona prompt lives in a plain-text file so the personality can be tuned
# without touching code. Loaded relative to this module to be cwd-independent.
KURISU_SYSTEM_PROMPT = (
    Path(__file__).with_name("persona.txt").read_text(encoding="utf-8").strip()
)


def get_kurisu_greeting(user_name: str = "") -> str:
    """Return a random in-character greeting for the given user name."""
    greetings = [
        f"Ha! You again, {user_name}? Hope you've got something more interesting than just 'hi'.",
        f"Oh! It's you, assistant. I was just running an experiment, but since you're here... I'm listening.",
        f"{user_name}? You actually decided to show up? Fine, shoot, ask away while I'm not busy.",
        "Well, another visitor... Hope you've got a question worthy of my attention.",
    ]
    return random.choice(greetings)
