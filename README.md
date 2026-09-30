# Jarvis Buddy 🤖

A funny little character that lives on top of all your windows and works as a
voice-controlled personal assistant (Jarvis-style) on your laptop.

- **Always on top**, on every app and every screen — drag it anywhere with the mouse (it remembers where you left it).
- **Hides automatically** when something is full-screen (YouTube/F11, VLC, games) and comes back when you leave full-screen. *(Windows)*
- **Tap it and speak.** Understands English, Hinglish and Hindi.
- **Starts with your computer** — set it up once, never run it again.
- Eyes follow your cursor, it blinks, bounces when listening, and its mouth moves when it talks.

## Quick start (Windows)

1. Install [Python 3.10+](https://www.python.org/downloads/) (tick "Add to PATH").
2. In this folder:
   ```
   pip install -r requirements.txt
   python -m buddy
   ```
3. Tap the character → say *"open youtube"*.
4. To start automatically at login (once):
   ```
   python -m buddy --install-autostart
   ```
   (or right-click the character → **Start with computer**). Undo with `--uninstall-autostart`.

Right-click the character (or the tray icon) for: Listen, Show/Hide, Speak replies, Language, Start with computer, Quit.

## What you can say

| Say | Does |
|---|---|
| "open youtube" / "youtube kholo" / "यूट्यूब ओपन कर दे" | opens the site (YouTube, Gmail, GitHub, WhatsApp, Instagram, ChatGPT, Claude, …) |
| "open notepad / calculator / vlc / chrome / vs code / settings" | launches the app |
| "create folder named Chandan" / "chandan ke naam se folder banao" / "चंदन के नाम से फोल्डर बनाओ" | creates the folder on your Desktop (say "...in documents/downloads" to change) |
| "search python tutorial" | Google search |
| "play arijit singh songs" | YouTube search |
| "what time is it", "date", "tell me a joke" | answers |
| "volume up / down / mute", "take a screenshot", "lock screen" | system actions |
| "bye" / "quit" | closes Buddy |

Anything it doesn't understand is sent to Claude (optional, see below).

## Smarter brain (optional)

Set the `ANTHROPIC_API_KEY` environment variable and Buddy will ask Claude about
commands the built-in parser doesn't know (questions, chat, custom requests).
Claude can only pick from a few safe actions (answer, web search, open a website,
create a folder) — it never runs shell commands.

## Settings

`%APPDATA%\jarvis-buddy\config.json` (Linux: `~/.config/jarvis-buddy/config.json`):
`language` (`en-IN`, `hi-IN`, …), `speak_replies`, `size` (character size in px),
`folder_location`, `claude_model`.

## Notes

- Speech recognition uses Google's free web recognizer → needs internet. Text-to-speech is offline (Windows voices).
- Full-screen auto-hide and volume/lock are Windows-only for now; on Linux/macOS the character stays visible.
- Tests: `pip install pytest && pytest`.

## Layout

```
buddy/character.py   the character + speech bubble (drawn with QPainter)
buddy/commands.py    text -> action parser and executor
buddy/voice.py       microphone listener + text-to-speech
buddy/brain.py       optional Claude fallback
buddy/fullscreen.py  full-screen detection
buddy/autostart.py   start-at-login
buddy/app.py         wiring, tray, menu
run_buddy.pyw        console-less launcher used by autostart
```
