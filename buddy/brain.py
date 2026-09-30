"""Optional smarter fallback: ask Claude what to do with a command the parser didn't get.

Enabled only when ANTHROPIC_API_KEY is set and the `anthropic` package is installed.
Claude can only choose from a small, safe set of actions -- it never runs shell commands.
"""

from __future__ import annotations

import json
import os
import re

from .commands import Action

SYSTEM = """You are the brain of a small desktop voice assistant called Buddy. The user is Chandan.
The user's speech was transcribed and our rule-based parser did not understand it.
Reply with ONE JSON object and nothing else, choosing exactly one of:
  {"action":"say","text":"..."}            - answer a question / chat (max 2 short sentences, friendly and a bit funny)
  {"action":"search","query":"..."}        - open a Google search
  {"action":"open_url","url":"https://..."}- open a website
  {"action":"create_folder","name":"..."}  - create a folder
Speak in the same language style as the user (English / Hinglish / Hindi)."""


def available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def ask(text: str, model: str) -> Action | None:
    if not available():
        return None
    import anthropic

    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=300,
            system=SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        return to_action(raw)
    except Exception:
        return None


def to_action(raw: str) -> Action | None:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    kind = data.get("action")
    if kind == "say" and data.get("text"):
        return Action("say", {"text": str(data["text"])})
    if kind == "search" and data.get("query"):
        return Action("search", {"query": str(data["query"])})
    if kind == "open_url" and str(data.get("url", "")).startswith(("http://", "https://")):
        return Action("open_url", {"url": data["url"], "label": "Website"})
    if kind == "create_folder" and data.get("name"):
        name = re.sub(r'[\\/:*?"<>|]', "", str(data["name"])).strip()
        if name:
            return Action("create_folder", {"name": name, "location": None})
    return None
