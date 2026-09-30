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
    "anthropic_api_key": "",  # set from the menu; stored in this file
    "asked_key": False,
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
