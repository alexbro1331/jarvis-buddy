"""Tiny append-only log so problems on your PC can be diagnosed (%APPDATA%/jarvis-buddy/buddy.log)."""

from __future__ import annotations

import datetime as dt

from .config import config_dir


def log(msg: str) -> None:
    try:
        path = config_dir() / "buddy.log"
        if path.exists() and path.stat().st_size > 200_000:  # keep it small
            path.write_text("", encoding="utf-8")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except OSError:
        pass
