"""The assistant's brain: an LLM with a small, safe set of tools and a short memory.

Providers are tried in order (free ones first): Gemini, Groq, Ollama (local), Claude. If one is
rate-limited or unreachable the next takes over. Whatever the provider, the model can only act
through the tools below -- it never gets a shell, and it cannot delete or overwrite anything.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Callable

from . import commands, providers
from .config import config_dir

MAX_TURNS = 6  # past user/assistant exchanges kept as conversation memory
MAX_TOOL_ROUNDS = 6

SYSTEM = """You are {name}, a funny, warm personal voice assistant living on {user}'s laptop screen as a cartoon character with {user}'s face. Think Jarvis with a great sense of humour.

Your replies are SPOKEN by a text-to-speech voice, so:
- Speak like a real friend: short, natural, conversational, one to three sentences. No markdown, lists, emojis, symbols or URLs.
- Language: mirror {user}. If they speak Hindi or Hinglish, reply in natural Hinglish written with Hindi words in Devanagari and English words in Latin letters, e.g. "मैंने YouTube खोल दिया, enjoy करो!". This is important: Roman-letter Hindi sounds robotic when spoken. If they speak plain English, reply in English.
- Light jokes and friendly teasing are welcome, but be serious when {user} is stressed or asks something serious.

Actions: you can control the computer with your tools (open sites/apps, search, play on YouTube, create folders, list files, timers, volume/screenshot/lock, remember facts). When asked for something a tool can do, call it immediately, then confirm briefly. For questions, answer from your own knowledge; if it needs live information (news, scores, prices, weather) say so and offer a web search, or run it if asked.
Speech recognition is imperfect: guess garbled app, site and song names from context and act; only ask when a wrong guess would be costly. You cannot delete files, run arbitrary commands, send messages or spend money.

What you remember about {user}:
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
        self.calls = 0  # tools executed so far (used to avoid repeating actions on provider fallback)

    def run(self, name: str, args: dict) -> str:
        self.calls += 1
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


ORDER = ["gemini", "groq", "ollama", "claude"]  # free first, paid last


def claude_key(cfg) -> str | None:
    return (cfg.data.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY") or "").strip() or None


def claude_ready(cfg) -> bool:
    if not claude_key(cfg):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def usable_providers(cfg) -> list[str]:
    """Providers that are set up, in the order they will be tried."""
    order = [p for p in cfg.data.get("brain_order", ORDER) if p in ORDER]
    return [p for p in order if (claude_ready(cfg) if p == "claude" else providers.configured(cfg, p))]


def available(cfg) -> bool:
    return bool(usable_providers(cfg))


_THINK = re.compile(r"<think>.*?</think>", re.S)


class Brain:
    def __init__(self, cfg, on_timer: Callable[[float, str], None] | None = None, client=None):
        self.cfg = cfg
        self.notes = Notes()
        self.tools = Toolbox(cfg, self.notes, on_timer)
        self.history: list[dict] = []
        self._client = client  # Claude client (injectable for tests)
        self.last_provider: str | None = None

    def reset_client(self) -> None:
        self._client = None

    def ask(self, text: str) -> str:
        """Answer `text`, running tools as needed. Returns the spoken reply. Blocking."""
        now = dt.datetime.now().strftime("%A, %d %B %Y, %I:%M %p")
        system = SYSTEM.format(name=self.cfg["name"], user=self.cfg["user_name"], notes=self.notes.text())
        stamped = f"[{now}] {text}"

        problems: list[str] = []
        for name in usable_providers(self.cfg):
            ran_before = self.tools.calls
            try:
                if name == "claude":
                    reply = self._claude_loop(system, stamped)
                else:
                    reply = self._openai_loop(name, system, stamped)
            except providers.AuthFailed:
                problems.append(f"{name}: key galat")
                continue
            except (providers.RateLimited, providers.Unavailable) as e:
                problems.append(str(e))
                if self.tools.calls != ran_before:
                    break  # an action already ran; don't risk repeating it on another provider
                continue
            self.last_provider = name
            self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
            self.history = self.history[-2 * MAX_TURNS:]
            return reply

        if any("rate limit" in p for p in problems):
            return "आज की free limit थोड़ी भर गई है, कुछ देर बाद try करो या menu से दूसरी API key जोड़ दो।"
        if any("key galat" in p for p in problems):
            return "API key सही नहीं लग रही। Menu से दोबारा key डाल दो।"
        return "इंटरनेट या AI service तक नहीं पहुँच पा रहा, थोड़ी देर बाद try करो।"

    # -- OpenAI-compatible providers (Gemini, Groq, Ollama) ---------------------------------
    def _openai_loop(self, name: str, system: str, user_text: str) -> str:
        msgs = [{"role": "system", "content": system}] + list(self.history) + [{"role": "user", "content": user_text}]
        tools = providers.to_openai_tools(TOOLS)
        for _ in range(MAX_TOOL_ROUNDS):
            m = providers.chat(self.cfg, name, msgs, tools)
            calls = m.get("tool_calls") or []
            if not calls:
                reply = _THINK.sub("", m.get("content") or "").strip()
                return reply or "हो गया!"
            msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
            for i, c in enumerate(calls):
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                msgs.append({
                    "role": "tool",
                    "tool_call_id": c.get("id") or f"call_{i}",
                    "content": self.tools.run(c["function"]["name"], args),
                })
        return "काम थोड़ा लंबा हो गया, दोबारा बोलो?"

    # -- Claude -----------------------------------------------------------------------------
    def _claude_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=claude_key(self.cfg))
        return self._client

    def _claude_loop(self, system: str, user_text: str) -> str:
        import anthropic

        messages = list(self.history) + [{"role": "user", "content": user_text}]
        try:
            client = self._claude_client()
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
                    return "इस वाले सवाल में मैं मदद नहीं कर सकता।"
                tool_calls = [b for b in resp.content if b.type == "tool_use"]
                if resp.stop_reason != "tool_use" or not tool_calls:
                    text = "".join(b.text for b in resp.content if b.type == "text").strip()
                    return text or "हो गया!"
                messages.append({"role": "assistant", "content": resp.content})
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": b.id, "content": self.tools.run(b.name, b.input)}
                        for b in tool_calls
                    ],
                })
        except anthropic.AuthenticationError as e:
            raise providers.AuthFailed("claude") from e
        except anthropic.RateLimitError as e:
            raise providers.RateLimited("claude: rate limit") from e
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            raise providers.Unavailable(f"claude: {e}") from e
        return "काम थोड़ा लंबा हो गया, दोबारा बोलो?"
