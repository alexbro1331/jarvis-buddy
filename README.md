# Jarvis Buddy 🤖

A funny cartoon character — with **your own face** — that lives on top of all your windows and works as a
voice-controlled AI personal assistant (Jarvis-style) on your laptop.

- **Always on top**, every app, every screen — drag it anywhere with the mouse (it remembers where you left it).
- **Hides automatically** when something is full-screen (YouTube/F11, VLC, games) and comes back afterwards. *(Windows)*
- **Tap it and speak** in English, Hinglish or Hindi. It answers out loud in a natural neural voice.
- **Real AI brain, free:** Gemini or Groq free tiers (or a model running on your own PC with Ollama). Ask anything,
  chat, or give it tasks — it opens sites/apps, creates folders, plays music, sets timers, remembers things about
  you, and more. Claude is supported too (optional, paid).
- **Starts with your computer** — set it up once, never run it again.
- Eyes-on-you bobblehead: bounces when listening, scratches its head when thinking, waves its arms and moves its
  mouth when talking, blinks, sticks its tongue out now and then.

## Quick start (Windows)

1. Install [Python 3.10+](https://www.python.org/downloads/) (tick "Add to PATH").
2. In this folder:
   ```
   pip install -r requirements.txt
   python -m buddy
   ```
   On first start Buddy asks you to pick a photo (clear, front-facing) and builds your cartoon face on the spot.
   Change it any time: right-click Buddy → **Change my face…**.
3. On first start Buddy asks for a free **API key** — see "Free AI setup" below (2 minutes, no credit card).
   Paste it and it becomes a real AI assistant. (Skip it and add it later from the right-click menu → **AI keys**.)
4. Tap the character and talk: *"open youtube"*, *"mujhe ek joke sunao"*, *"5 minute baad chai yaad dilana"*.
5. Start automatically at login (once): `python -m buddy --install-autostart`
   (or right-click the character → **Start with computer**). Undo with `--uninstall-autostart`.

Right-click the character (or the tray icon) for: Listen, Show/Hide, Speak replies, AI keys, Speech recognition,
Local AI (Ollama), Voice (male/female), Language, Start with computer, Quit.

## Your cartoon face

Right-click → **Change my face…** (or `python -m buddy --make-avatar photo.jpg`) finds the face in any photo (front-facing works best), cuts out the head,
gives it a painted-cartoon look and writes `assets/head.png` + `assets/head.json`. It all runs on your computer —
the photo is never uploaded. Those two files are in `.gitignore` so your face doesn't end up on GitHub by accident.
Without them Buddy shows a built-in cartoon blob instead.

Want a fancier 3D look? Generate a cartoon head in any image tool (Canva, etc.), save it as a transparent PNG and
run `--make-avatar` on it, or replace `assets/head.png` directly (keep `head.json`'s eye/mouth positions in sync).

## Free AI setup (recommended: both keys)

| What | Service | How to get it | Free allowance* |
|---|---|---|---|
| AI brain + **best speech recognition** | **Groq** | <https://console.groq.com/keys> (no card) | chat: 1,000 requests/day and ~200k tokens/day on gpt-oss models; Whisper speech-to-text: ~8 hours of audio/day |
| AI brain (backup, more generous) | **Gemini** (Flash-Lite) | <https://aistudio.google.com/apikey> (no card) | ~500 requests/day on Flash-Lite models; limits change often |
| Offline, unlimited | **Ollama** on your PC | <https://ollama.com/download>, then `ollama pull qwen3:8b`, then tick **Local AI** in the menu | only your PC's speed |
| Offline speech recognition | **faster-whisper** | `pip install faster-whisper`, then menu → Speech recognition → "On this PC" | unlimited (downloads a ~500 MB model once) |

\* Free-tier numbers come from third-party write-ups (mid-2026) and change without notice; your real limits are shown in each
provider's console. Buddy tries Gemini → Groq → Ollama → Claude and moves to the next one automatically when a limit is hit
or the internet drops, so two free keys comfortably cover normal daily use. Model names are configurable
(`gemini_model`, `groq_model`, `ollama_model` in the config) and Buddy re-discovers a working model if one is retired.

Why Groq for listening? Its hosted Whisper understands Hindi, English and Hinglish far better than the basic recognizer
(which is still used as the fallback). Keys are stored only in your local config file.

## Natural voice

Buddy speaks with Microsoft neural voices (`edge-tts`, free, internet needed). The big trick against the "robot" sound:
replies are written with **Hindi words in Devanagari and English words in Latin letters** ("मैंने YouTube खोल दिया"),
and Devanagari text is spoken by a real Hindi voice. (Hindi written in Roman letters is read with an English accent,
which is what sounds robotic.) Markdown, emojis and links are stripped before speaking. If the natural voice can't
start, the bubble tells you why instead of silently switching to the system voice. Switch male/female in the menu.

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

The AI acts only through a small list of tools (open a site/app, search, create a folder, list Desktop/Documents/Downloads,
timers, volume/screenshot/lock, remember a note). It has **no shell, cannot delete, overwrite or send anything**.
API keys are stored in `%APPDATA%\jarvis-buddy\config.json` on your machine (the `ANTHROPIC_API_KEY` environment
variable also works for Claude). Don't share that file.

## Settings

`%APPDATA%\jarvis-buddy\config.json` (Linux: `~/.config/jarvis-buddy/config.json`):
`user_name`, `language`, `speak_replies`, `voice_gender`, `size` (px), `folder_location`, `brain_order`,
`stt_engine` (`auto`/`groq`/`local`/`google`), `stt_language` (`""` = auto, or `hi` / `en`), `gemini_model`, `groq_model`,
`ollama_model`, `claude_model` (default `claude-opus-5-5`; `claude-sonnet-5-5` is cheaper).

## Quick commands

```
python -m buddy --set-key groq YOUR_GROQ_KEY       # save a free key (also: gemini, claude)
python -m buddy --set-key gemini YOUR_GEMINI_KEY
python -m buddy --voices                            # hear the same sentence in several natural voices
python -m buddy --set-voice en-US-AvaMultilingualNeural   # keep the one you like ('auto' resets)
python -m buddy --diagnose                          # checks everything on your PC
```

## Something not working? Run the diagnosis

```
python -m buddy --diagnose
```
It checks packages, microphone, the natural voice (and plays a sample), your AI keys and the photo tool on *your* PC,
and tells you exactly which part fails and why. Errors are also written to `%APPDATA%\jarvis-buddy\buddy.log`.
The speech bubble shows what **you** said (blue, on top) and Buddy's reply (white, below it).

## Notes

- Listening: Groq Whisper when a Groq key exists (auto-detects Hindi/English), otherwise Google's free recognizer;
  if the chosen engine is rate-limited or offline it falls back to Google. What it heard is shown in the speech bubble.
- Speaking needs internet for the natural voice; offline it falls back to the Windows system voice.
- Full-screen auto-hide, volume and lock are Windows-only for now.
- Tests: `pip install pytest && pytest`.

## Layout

```
buddy/character.py   the character (photo bobblehead or blob) + speech bubble
buddy/avatar.py      photo -> cartoon head
buddy/brain.py       LLM with tools + memory, provider fallback
buddy/providers.py   Gemini / Groq / Ollama chat, Groq + local Whisper speech-to-text
buddy/commands.py    instant local command parser
buddy/voice.py       microphone listener + text-to-speech
buddy/fullscreen.py  full-screen detection
buddy/autostart.py   start-at-login
buddy/app.py         wiring, tray, menu
run_buddy.pyw        console-less launcher used by autostart
```
