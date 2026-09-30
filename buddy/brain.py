"""The assistant's brain: Claude with a small, safe set of tools and a short memory.

Needs an API key (menu -> "Set Claude API key", or the ANTHROPIC_API_KEY env var).
Claude can only act through the tools below -- it never gets a shell, and it cannot
delete or overwrite anything.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Callable

from . import commands
from .config import config_dir

MAX_TURNS = 10  # past user/assistant exchanges kept as conversation memory
MAX_TOOL_ROUNDS = 6

SYSTEM = """You are {name}, a funny, warm personal voice assistant that lives on {user}'s laptop screen as a cartoon character with {user}'s face. Think Jarvis, but with a great sense of humour.

How to behave:
- Your replies are spoken aloud by a text-to-speech voice, so write plain spoken sentences: no markdown, no bullet lists, no emojis, no URLs read out. Keep it to one to three short sentences unless {user} asks for detail.
- Match {user}'s language: English, Hinglish (Hindi in Roman letters) or Hindi. If {user} wrote in Devanagari, answer in Devanagari; if in Hinglish or English, answer in Roman letters. Light, friendly jokes and a little teasing are welcome, never at {user}'s expense when they are stressed or asking something serious.
- You can take actions on the computer with your tools. When {user} asks for something a tool can do (open a site or app, search, play something, create a folder, timers, volume, screenshots, remembering things), call the tool right away instead of asking for permission, then confirm briefly what you did.
- For questions, just answer from your own knowledge. If you are unsure or the answer needs live information (news, scores, prices, weather), say so and offer to search the web, or do the search if they asked.
- Speech recognition is imperfect: if the request is garbled, make your best guess from context (names of apps, sites and songs are often misheard) and act; only ask a clarifying question when a wrong guess would be costly.
- You cannot delete files, run arbitrary commands, send messages or spend money. If asked, say so in a friendly way.

Things you remember about {user}:
{notes}
"""

TOOLS = [
    {
        "name": "open_website",
        "description": "Open a website in the default browser. Use for 'open youtube', 'go to github', etc.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Full URL starting with https://"}},
            "required": ["url"],
        },
    },
    {
        "name": "open_app",
        "description": "Launch a desktop application by name (notepad, calculator, chrome, vlc, vs code, word, excel, settings, file explorer, ...).",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "search_web",
        "description": "Open a Google search for a query in the browser.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "play_youtube",
        "description": "Open YouTube search results for a song, video or topic so the user can play it.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "create_folder",
        "description": "Create a new folder. Does nothing if it already exists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Folder name, no slashes"},
                "location": {"type": "string", "enum": ["Desktop", "Documents", "Downloads"], "description": "Defaults to the user's preferred location"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_files",
        "description": "List the file and folder names inside Desktop, Documents or Downloads (read-only).",
        "input_schema": {
            "type": "object",
            "properties": {"folder": {"type": "string", "enum": ["Desktop", "Documents", "Downloads"]}},
            "required": ["folder"],
        },
    },
    {
        "name": "system_control",
        "description": "Volume up/down/mute, take a screenshot (saved to Pictures), or lock the screen.",
        "input_schema": {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["volume_up", "volume_down", "mute", "screenshot", "lock"]}},
            "required": ["action"],
        },
    },
    {
        "name": "set_timer",
        "description": "Set a reminder/timer. The character will speak up when it fires.",
        "input_schema": {
            "type": "object",
            "properties": {
                "minutes": {"type": "number", "description": "Minutes from now (can be fractional)"},
                "label": {"type": "string", "description": "What to remind the user about"},
            },
            "required": ["minutes", "label"],
        },
    },
    {
        "name": "remember",
        "description": "Save a short fact about the user (name of a friend, preference, birthday...) so it is remembered in future conversations.",
        "input_schema": {
            "type": "object",
            "properties": {"note": {"type": "string"}},
            "required": ["note"],
        },
    },
]


class Notes:
    """Tiny persistent memory (a JSON list of strings)."""

    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "notes.json"
        try:
            self.items: list[str] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.items = []

    def add(self, note: str) -> None:
        note = note.strip()
        if note and note not in self.items:
            self.items = (self.items + [note])[-50:]
            try:
                self.path.write_text(json.dumps(self.items, ensure_ascii=False, indent=1), encoding="utf-8")
            except OSError:
                pass

    def text(self) -> str:
        return "\n".join(f"- {n}" for n in self.items) or "(nothing yet)"


class Toolbox:
    """Runs the tools Claude asks for. Every method returns a short result string."""

    def __init__(self, cfg, notes: Notes, on_timer: Callable[[float, str], None] | None = None):
        self.cfg, self.notes, self.on_timer = cfg, notes, on_timer

    def run(self, name: str, args: dict) -> str:
        try:
            fn = getattr(self, f"_t_{name}", None)
            return fn(**args) if fn else f"Unknown tool {name}"
        except TypeError as e:
            return f"Bad arguments: {e}"
        except Exception as e:  # tool errors go back to Claude, not up to the UI
            return f"Error: {e}"

    def _t_open_website(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        return f"Opened {url}"

    def _t_open_app(self, name: str) -> str:
        return commands.execute(commands._open_target(commands._norm(name)), self.cfg)

    def _t_search_web(self, query: str) -> str:
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
        return f"Opened Google search for: {query}"

    def _t_play_youtube(self, query: str) -> str:
        webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query))
        return f"Opened YouTube results for: {query}"

    def _t_create_folder(self, name: str, location: str | None = None) -> str:
        name = "".join(c for c in name if c not in '\\/:*?"<>|').strip()
        if not name:
            return "Invalid folder name."
        return commands.execute(commands.Action("create_folder", {"name": name, "location": location}), self.cfg)

    def _t_list_files(self, folder: str) -> str:
        base = commands._known_folder(folder)
        names = sorted(p.name + ("/" if p.is_dir() else "") for p in base.iterdir() if not p.name.startswith("."))
        if not names:
            return "(empty)"
        return ", ".join(names[:60]) + (f" ... (+{len(names) - 60} more)" if len(names) > 60 else "")

    def _t_system_control(self, action: str) -> str:
        table = {
            "volume_up": commands.Action("volume", {"dir": "up"}),
            "volume_down": commands.Action("volume", {"dir": "down"}),
            "mute": commands.Action("volume", {"dir": "mute"}),
            "screenshot": commands.Action("screenshot"),
            "lock": commands.Action("lock"),
        }
        return commands.execute(table[action], self.cfg) if action in table else "Unknown action"

    def _t_set_timer(self, minutes: float, label: str) -> str:
        if self.on_timer is None:
            return "Timers are not available right now."
        minutes = max(0.1, min(float(minutes), 24 * 60))
        self.on_timer(minutes, label)
        return f"Timer set for {minutes:g} minutes: {label}"

    def _t_remember(self, note: str) -> str:
        self.notes.add(note)
        return "Saved."


def api_key(cfg) -> str | None:
    return (cfg.data.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY") or "").strip() or None


def available(cfg) -> bool:
    if not api_key(cfg):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


class Brain:
    def __init__(self, cfg, on_timer: Callable[[float, str], None] | None = None, client=None):
        self.cfg = cfg
        self.notes = Notes()
        self.tools = Toolbox(cfg, self.notes, on_timer)
        self.history: list[dict] = []
        self._client = client

    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=api_key(self.cfg))
        return self._client

    def reset_client(self) -> None:
        self._client = None

    def ask(self, text: str) -> str:
        """Answer `text`, running tools as needed. Returns the spoken reply. Blocking."""
        import anthropic

        now = dt.datetime.now().strftime("%A, %d %B %Y, %I:%M %p")
        system = SYSTEM.format(name=self.cfg["name"], user=self.cfg["user_name"], notes=self.notes.text())
        messages = list(self.history) + [{"role": "user", "content": f"[{now}] {text}"}]

        try:
            reply = self._loop(system, messages)
        except anthropic.AuthenticationError:
            return "Claude API key galat lag rahi hai. Menu se dobara key daal do."
        except anthropic.RateLimitError:
            return "Abhi Claude thoda busy hai, ek minute baad try karo."
        except anthropic.APIConnectionError:
            return "Internet ya Claude tak nahi pahunch pa raha."
        except anthropic.APIStatusError as e:
            return f"Claude se dikkat aayi: {getattr(e, 'message', e)}"

        self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        self.history = self.history[-2 * MAX_TURNS:]
        return reply

    def _loop(self, system: str, messages: list) -> str:
        client = self._get_client()
        for _ in range(MAX_TOOL_ROUNDS):
            resp = client.beta.messages.create(
                model=self.cfg["claude_model"],
                max_tokens=1024,
                system=system,
                tools=TOOLS,
                messages=messages,
                output_config={"effort": "low"},  # fast replies; this is a voice assistant
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",  # re-run on another model if a safety classifier false-positives
            )
            if resp.stop_reason == "refusal":
                return "Is wale sawaal mein main madad nahi kar sakta."
            tool_calls = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not tool_calls:
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                return text or "Ho gaya!"
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": b.id, "content": self.tools.run(b.name, b.input)}
                    for b in tool_calls
                ],
            })
        return "Kaam thoda lamba ho gaya, dobara bolo?"
