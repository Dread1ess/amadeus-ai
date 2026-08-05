"""Kurisu's persona: the system prompt loaded from persona.txt."""

from pathlib import Path

# The persona prompt lives in a plain-text file so the personality can be tuned
# without touching code. Loaded relative to this module to be cwd-independent.
KURISU_SYSTEM_PROMPT = (
    Path(__file__).with_name("persona.txt").read_text(encoding="utf-8").strip()
)
