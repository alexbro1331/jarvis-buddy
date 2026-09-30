# Jarvis Buddy 🤖

A funny cartoon character — with **your own face** — that lives on top of all your windows and works as a
voice-controlled AI personal assistant (Jarvis-style) on your laptop.

- **Always on top**, every app, every screen — drag it anywhere with the mouse (it remembers where you left it).
- **Hides automatically** when something is full-screen (YouTube/F11, VLC, games) and comes back afterwards. *(Windows)*
- **Tap it and speak** in English, Hinglish or Hindi. It answers out loud in a natural neural voice.
- **Real AI brain (Claude):** ask anything, chat, or give it tasks — it opens sites/apps, creates folders, plays music,
  sets timers, remembers things about you, and more.
- **Starts with your computer** — set it up once, never run it again.
- Eyes-on-you bobblehead: bounces when listening, scratches its head when thinking, waves its arms and moves its
  mouth when talking, blinks, sticks its tongue out now and then.

## Quick start (Windows)

1. Install [Python 3.10+](https://www.python.org/downloads/) (tick "Add to PATH").
2. In this folder:
   ```
   pip install -r requirements.txt
   python -m buddy --make-avatar C:\path\to\your\photo.jpg     # builds your cartoon face (runs locally)
   python -m buddy
   ```
3. On first start Buddy asks for a **Claude API key** (from <https://console.anthropic.com>). Paste it — that's what
   makes it a real AI assistant. (Skip it and you can add it later from the right-click menu.)
4. Tap the character and talk: *"open youtube"*, *"mujhe ek joke sunao"*, *"5 minute baad chai yaad dilana"*.
5. Start automatically at login (once): `python -m buddy --install-autostart`
   (or right-click the character → **Start with computer**). Undo with `--uninstall-autostart`.

Right-click the character (or the tray icon) for: Listen, Show/Hide, Speak replies, Claude API key, Voice (male/female),
Language, Start with computer, Quit.

## Your cartoon face

`python -m buddy --make-avatar photo.jpg` finds the face in any photo (front-facing works best), cuts out the head,
gives it a painted-cartoon look and writes `assets/head.png` + `assets/head.json`. It all runs on your computer —
the photo is never uploaded. Those two files are in `.gitignore` so your face doesn't end up on GitHub by accident.
Without them Buddy shows a built-in cartoon blob instead.

Want a fancier 3D look? Generate a cartoon head in any image tool (Canva, etc.), save it as a transparent PNG and
run `--make-avatar` on it, or replace `assets/head.png` directly (keep `head.json`'s eye/mouth positions in sync).

## What you can say

Simple commands run instantly; anything else goes to Claude (which can also use the same actions).

| Say | Does |
|---|---|
| "open youtube" / "youtube kholo" / "यूट्यूब ओपन कर दे" | opens the site (YouTube, Gmail, GitHub, WhatsApp, ChatGPT, Claude, …) |
| "open notepad / calculator / vlc / chrome / vs code / settings" | launches the app |
| "create folder named Chandan" / "chandan ke naam se folder banao" | creates the folder on your Desktop ("…in documents/downloads" to change) |
| "play arijit singh songs" | YouTube search |
| "what's in my downloads folder" *(AI)* | lists file names (read-only) |
| "5 minute baad chai yaad dilana" *(AI)* | timer — Buddy speaks up when it's time |
| "remember that my sister's birthday is 12 March" *(AI)* | remembered across restarts |
| "volume up / down / mute", "take a screenshot", "lock screen" | system actions |
| any question or chat *(AI)* | answered in your language, with some humour |
| "bye" / "quit" | closes Buddy |

Without an API key, anything Buddy doesn't know is searched on Google instead of a dead-end "didn't understand".

## Safety

Claude acts only through a small list of tools (open a site/app, search, create a folder, list Desktop/Documents/Downloads,
timers, volume/screenshot/lock, remember a note). It has **no shell, cannot delete, overwrite or send anything**.
The API key is stored in `%APPDATA%\jarvis-buddy\config.json` on your machine (or use the `ANTHROPIC_API_KEY`
environment variable instead).

## Settings

`%APPDATA%\jarvis-buddy\config.json` (Linux: `~/.config/jarvis-buddy/config.json`):
`user_name`, `language` (`en-IN`, `hi-IN`, …), `speak_replies`, `voice_gender`, `size` (character size in px),
`folder_location`, `claude_model` (default `claude-opus-5-5`; `claude-sonnet-5-5` is cheaper).

## Notes

- Listening uses Google's free speech recognizer (internet needed). It tries your language first, then the other
  one, so Hinglish works better. Speak clearly and close to the mic; what it heard is shown in the speech bubble.
- Speaking uses Microsoft neural voices through `edge-tts` (internet needed); offline it falls back to the
  Windows system voice. Hindi (Devanagari) replies use a Hindi voice, everything else an Indian-English voice.
- Full-screen auto-hide, volume and lock are Windows-only for now.
- Tests: `pip install pytest && pytest`.

## Layout

```
buddy/character.py   the character (photo bobblehead or blob) + speech bubble
buddy/avatar.py      photo -> cartoon head
buddy/brain.py       Claude with tools + memory
buddy/commands.py    instant local command parser
buddy/voice.py       microphone listener + text-to-speech
buddy/fullscreen.py  full-screen detection
buddy/autostart.py   start-at-login
buddy/app.py         wiring, tray, menu
run_buddy.pyw        console-less launcher used by autostart
```
