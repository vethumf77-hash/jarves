"""Saves the settings you change inside the app, and loads them again on the next launch.

Anything editable in the Settings window is stored in settings.json (next to the
app) and written back onto the `config` module at startup, so every other file
keeps reading plain `config.SOMETHING` exactly as before. config.py still holds
the defaults. Your Groq API key is the one exception: it goes in .env, like
before, never in settings.json.
"""
import json
import os
import re
from pathlib import Path

import config
import paths

APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = paths.DATA_DIR / "settings.json"
ENV_PATH = paths.DATA_DIR / ".env"

# name in config.py -> type it should have
EDITABLE = {
    "GROQ_CHAT_MODEL": str,
    "GROQ_STT_MODEL": str,
    "WAKE_WORD_THRESHOLD": float,
    "SILENCE_SECONDS": float,
    "HAND_MOUSE_HOTKEY": str,
    "HAND_MOUSE_DEBUG_WINDOW": bool,
    "SPEAK_REPLIES": bool,
}


def _coerce(value, kind):
    if kind is bool:
        return bool(value)
    return kind(value)


def load() -> None:
    """Applies settings.json (if it exists) on top of config.py's defaults."""
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for name, kind in EDITABLE.items():
        if name in data:
            try:
                setattr(config, name, _coerce(data[name], kind))
            except (TypeError, ValueError):
                pass


def current() -> dict:
    """The values the Settings window should show right now."""
    return {name: getattr(config, name, None) for name in EDITABLE}


def save(values: dict) -> None:
    """Applies new values to config immediately and remembers them for next launch."""
    clean = {}
    for name, kind in EDITABLE.items():
        if name in values:
            clean[name] = _coerce(values[name], kind)
            setattr(config, name, clean[name])
    try:
        existing = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = {}
    existing.update(clean)
    SETTINGS_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def get_api_key() -> str:
    return os.environ.get("GROQ_API_KEY", "").strip()


def save_api_key(key: str) -> None:
    """Writes GROQ_API_KEY into .env (keeping every other line) and into this process."""
    key = key.strip()
    lines = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(r"^\s*GROQ_API_KEY\s*=")
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"GROQ_API_KEY={key}"
            break
    else:
        lines.append(f"GROQ_API_KEY={key}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["GROQ_API_KEY"] = key
