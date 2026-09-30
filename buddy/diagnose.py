"""`python -m buddy --diagnose`: checks every part on THIS computer and prints a report you can paste back."""

from __future__ import annotations

import importlib
import platform
import sys

from . import avatar, providers
from .config import Config, config_dir
from .log import log
from .voice import CANDIDATE_VOICES, RATE, TtsError, play_mp3_windows, synthesize


def _line(ok: bool | None, what: str, detail: str = "") -> None:
    mark = {True: "[ OK ]", False: "[FAIL]", None: "[ -- ]"}[ok]
    msg = f"{mark} {what}" + (f"  ->  {detail}" if detail else "")
    print(msg)
    log("diagnose " + msg)


def run() -> int:
    cfg = Config()
    print(f"Jarvis Buddy diagnose   ({platform.platform()}, Python {sys.version.split()[0]})")
    print(f"Config/log folder: {config_dir()}\n")

    print("-- Packages")
    for mod, pip in (
        ("PyQt6", "PyQt6"), ("edge_tts", "edge-tts"), ("gtts", "gTTS"), ("pyttsx3", "pyttsx3"),
        ("sounddevice", "sounddevice"), ("speech_recognition", "SpeechRecognition"), ("requests", "requests"),
        ("cv2", "opencv-python-headless<4.11"), ("numpy", "numpy"),
    ):
        try:
            m = importlib.import_module(mod)
            extra = ""
            if mod == "cv2" and not hasattr(m, "CascadeClassifier"):
                _line(False, mod, f"version {m.__version__} is too new for --make-avatar: pip install \"opencv-python-headless<4.11\"")
                continue
            _line(True, mod, getattr(m, "__version__", extra))
        except Exception as e:
            _line(False, mod, f"{type(e).__name__}: {e}   (pip install {pip})")

    print("\n-- Character")
    _line(avatar.has_avatar(), "your face (assets/head.png)", "" if avatar.has_avatar() else "missing: right-click Buddy -> 'Change my face...' or run --make-avatar photo.jpg")

    print("\n-- Microphone")
    try:
        import sounddevice as sd

        dev = sd.query_devices(kind="input")
        _line(True, "default input device", dev["name"])
    except Exception as e:
        _line(False, "microphone", f"{type(e).__name__}: {e}")

    print("\n-- Voice (natural neural voice)")
    try:
        text = "नमस्ते चंदन, मैं Buddy हूँ। अब मेरी आवाज़ कैसी लग रही है?"
        path = synthesize(text, cfg["voice_gender"], cfg["voice_name"])
        _line(True, "speech generated", f"{path.stat().st_size} bytes")
        if sys.platform == "win32":
            print("       playing it now -- do you hear a natural voice?")
            _line(play_mp3_windows(str(path)), "played with Windows MCI player")
    except TtsError as e:
        _line(False, "natural voice", str(e))
        print("       -> this is why the voice sounds robotic (Buddy fell back to the system voice).")

    print("\n-- AI keys")
    print(f"       (read from {cfg.path})")
    for name in ("gemini", "groq"):
        if not providers.configured(cfg, name):
            _line(None, f"{name} chat", f"no key saved -> run: python -m buddy --set-key {name} YOUR_KEY")
            continue
        _line(True, f"{name} key saved", f"{len(providers.api_key(cfg, name))} characters")
        try:
            m = providers.chat(cfg, name, [{"role": "user", "content": "Reply with just: OK"}], None)
            _line(True, f"{name} chat", (m.get("content") or "").strip()[:40])
        except Exception as e:
            _line(False, f"{name} chat", f"{type(e).__name__}: {e}")
    if providers.api_key(cfg, "groq"):
        try:
            text = providers.transcribe_groq(cfg, b"\x00\x00" * RATE)  # 1 s of silence
            _line(True, "groq speech-to-text", f"reachable (heard: {text!r})")
        except Exception as e:
            _line(False, "groq speech-to-text", f"{type(e).__name__}: {e}")

    print(f"\nVoice in use: {cfg['voice_name'] or 'automatic (' + cfg['voice_gender'] + ')'}   (try others: python -m buddy --voices)")
    print(f"Speech engine in use: {cfg['stt_engine']}   |   Log file: {config_dir() / 'buddy.log'}")
    print("Paste this whole report back if something shows [FAIL].")
    return 0


def voices(cfg) -> int:
    """Play the same Hinglish sentence in several neural voices; the user picks the most natural one."""
    import asyncio

    text = "नमस्ते Chandan, मैं Buddy हूँ। आज मैं तुम्हारी क्या help कर सकता हूँ?"
    try:
        import edge_tts

        available = {v["ShortName"] for v in asyncio.run(edge_tts.list_voices())}
    except Exception as e:
        print(f"Could not reach the voice service: {type(e).__name__}: {e}")
        return 1
    names = [v for v in CANDIDATE_VOICES if v in available]
    if sys.platform != "win32":
        print("Sample playback is Windows-only; voices available:", ", ".join(names))
        return 0
    print("Listening test: the same sentence in each voice. Note the NUMBER of the one you like best.\n")
    played = []
    for i, name in enumerate(names, 1):
        try:
            print(f"  {i}. {name}")
            played.append(name)
            play_mp3_windows(str(synthesize(text, voice=name)))
        except Exception as e:
            print(f"     (skipped: {e})")
    print("\nPick one, e.g.:   python -m buddy --set-voice " + (played[0] if played else "en-US-AvaMultilingualNeural"))
    print("Reset to automatic: python -m buddy --set-voice auto")
    return 0
