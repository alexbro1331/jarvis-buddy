"""Persistent user settings (position, language, ...) stored as JSON."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    "name": "Buddy",
    "user_name": "Chandan",
    "language": "en-IN",  # speech recognition language; try "hi-IN" for Hindi
    "speak_replies": True,
    "voice_gender": "male",  # male / female (neural voices)
    "voice_name": "",  # exact voice, e.g. en-US-AndrewMultilingualNeural (pick with: python -m buddy --voices)
    # --- AI keys: set from the menu, stored in this file on your PC ---
    "gemini_api_key": "",  # free: https://aistudio.google.com/apikey
    "groq_api_key": "",  # free: https://console.groq.com/keys  (also gives free Whisper speech-to-text)
    "anthropic_api_key": "",  # optional, paid
    "use_ollama": False,  # run a local model with Ollama instead (free, offline)
    "brain_order": ["gemini", "groq", "ollama", "claude"],  # tried in this order; next one on rate limit
    "stt_engine": "auto",  # auto = Groq Whisper if a Groq key exists, else Google; or groq / local / google
    "stt_language": "",  # "" = auto-detect (best for Hinglish); or "hi" / "en"
    "local_stt_model": "small",  # faster-whisper model size for stt_engine "local"
    "asked_key": False,
    "asked_face": False,
    "pos": None,  # [x, y] of the character window
    "size": 200,
    "claude_model": "claude-opus-5-5",  # or "claude-sonnet-5-5" for cheaper/faster
    "folder_location": "Desktop",  # where "create folder" puts new folders
}


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / "jarvis-buddy"
    path.mkdir(parents=True, exist_ok=True)
    return path


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "config.json"
        self.data = dict(DEFAULTS)
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass
