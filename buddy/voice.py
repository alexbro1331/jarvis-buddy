"""Microphone listening (speech -> text) and realistic text-to-speech, off the UI thread."""

from __future__ import annotations

import asyncio
import re
import tempfile
import threading
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal

from . import providers
from .log import log

RATE = 16000

# Microsoft neural voices (via edge-tts). Hindi voices for Devanagari text, Indian-English voices
# for English / Hinglish written in Roman letters.
VOICES = {
    "male": {"hi": "hi-IN-MadhurNeural", "en": "en-IN-PrabhatNeural"},
    "female": {"hi": "hi-IN-SwaraNeural", "en": "en-IN-NeerjaNeural"},
}
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


_URL = re.compile(r"https?://\S+")
_MARKUP = re.compile(r"[*_`#>~|\[\]{}<>^]+")
_EMOJI = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]")


def clean_for_speech(text: str) -> str:
    """Strip everything a voice would read out awkwardly (markdown, emojis, links, stray symbols)."""
    text = _URL.sub(" ", text)
    text = _EMOJI.sub(" ", text)
    text = _MARKUP.sub(" ", text)
    text = re.sub(r"\s*[-\u2013\u2014]{2,}\s*", ", ", text)
    return re.sub(r"\s+", " ", text).strip()


def pick_voice(text: str, gender: str = "male") -> str:
    voices = VOICES.get(gender, VOICES["male"])
    return voices["hi"] if DEVANAGARI.search(text) else voices["en"]


class Listener(QObject):
    """Records one utterance, then transcribes it. Emits `heard(text)` or `failed(msg)`."""

    heard = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, language: str = "en-IN", cfg=None):
        super().__init__()
        self.language = language
        self.cfg = cfg
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def listen(self) -> None:
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            audio = self._record()
            if audio is None:
                self.failed.emit("Kuch sunai nahi diya. Mic ke paas bolo aur phir se tap karo.")
                return
            try:
                text = self._transcribe(audio)
            except providers.ProviderError:
                self.failed.emit("Internet nahi hai, awaaz samajhne ke liye internet chahiye.")
                return
            if not text:
                self.failed.emit("Awaaz clear nahi aayi. Thoda paas se aur saaf bolo.")
                return
            self.heard.emit(text)
        except Exception as e:  # mic missing, driver error, ...
            self.failed.emit(f"Mic problem: {e}")
        finally:
            self._busy = False

    # -- speech to text ---------------------------------------------------------------------
    def engine(self) -> str:
        choice = self.cfg.data.get("stt_engine", "auto") if self.cfg else "google"
        if choice == "auto":
            return "groq" if self.cfg and providers.api_key(self.cfg, "groq") else "google"
        return choice

    def _transcribe(self, pcm: bytes) -> str:
        """Best engine first (Groq Whisper / local Whisper), Google's free recognizer as the safety net."""
        engine = self.engine()
        try:
            if engine == "groq":
                return providers.transcribe_groq(self.cfg, pcm, RATE)
            if engine == "local":
                return providers.transcribe_local(self.cfg, pcm)
        except providers.ProviderError:
            pass  # rate limit / offline / bad key -> fall through to Google
        return self._transcribe_google(pcm)

    def _transcribe_google(self, pcm: bytes) -> str:
        import speech_recognition as sr

        data = sr.AudioData(pcm, RATE, 2)
        rec = sr.Recognizer()
        # Hinglish speakers are often recognised better by the other language model,
        # so try the configured language first and the other one as a backup.
        other = "hi-IN" if self.language.lower().startswith("en") else "en-IN"
        for lang in (self.language, other):
            try:
                return rec.recognize_google(data, language=lang)
            except sr.UnknownValueError:
                continue
            except sr.RequestError as e:
                raise providers.Unavailable("google stt") from e
        return ""

    def _record(self) -> bytes | None:
        """Record until the user stops talking. Returns raw 16-bit mono PCM or None."""
        import numpy as np
        import sounddevice as sd

        block = int(RATE * 0.1)  # 100 ms
        chunks: list = []
        noise: list[float] = []
        threshold = None
        started = False
        silence = 0
        waited = 0
        pre: list = []  # keep the last 0.3 s before speech starts so first syllables aren't clipped

        with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=block) as stream:
            while True:
                data, _ = stream.read(block)
                level = float(np.abs(data).mean())
                if threshold is None:
                    noise.append(level)
                    if len(noise) >= 4:  # first 0.4 s calibrates ambient noise
                        threshold = max(250.0, sum(noise) / len(noise) * 2.5)
                    continue
                if level > threshold:
                    if not started:
                        chunks.extend(pre)
                    started = True
                    silence = 0
                elif started:
                    silence += 1
                else:
                    waited += 1
                    pre = (pre + [data.copy()])[-3:]
                if started:
                    chunks.append(data.copy())
                if not started and waited > 80:  # 8 s of nothing
                    return None
                if started and (silence >= 12 or len(chunks) > 150):  # 1.2 s quiet / 15 s max
                    break
        return np.concatenate(chunks).tobytes() if chunks else None


# Voices worth auditioning: Hindi and Indian-English neural voices plus Microsoft's "multilingual" voices,
# which are the most human-sounding and can switch between Hindi and English mid-sentence.
CANDIDATE_VOICES = [
    "hi-IN-MadhurNeural", "hi-IN-SwaraNeural",
    "en-IN-PrabhatNeural", "en-IN-NeerjaNeural", "en-IN-NeerjaExpressiveNeural",
    "en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural",
    "en-US-AvaMultilingualNeural", "en-US-EmmaMultilingualNeural",
]


class TtsError(Exception):
    """No online voice could produce audio; the message lists why each one failed."""


def synthesize(text: str, gender: str = "male", voice: str = "") -> Path:
    """Text -> mp3 file. Microsoft neural voice first (most natural), Google's voice as backup."""
    out = Path(tempfile.mkdtemp(prefix="buddy-tts-")) / "say.mp3"
    reasons = []
    try:
        import edge_tts

        asyncio.run(edge_tts.Communicate(text, voice or pick_voice(text, gender), rate="+4%").save(str(out)))
        if out.exists() and out.stat().st_size > 500:
            return out
        reasons.append("edge-tts: empty audio")
    except Exception as e:
        reasons.append(f"edge-tts: {type(e).__name__}: {str(e)[:160]}")
    try:
        from gtts import gTTS

        gTTS(text, lang="hi" if DEVANAGARI.search(text) else "en", tld="co.in").save(str(out))
        if out.exists() and out.stat().st_size > 500:
            return out
        reasons.append("gTTS: empty audio")
    except Exception as e:
        reasons.append(f"gTTS: {type(e).__name__}: {str(e)[:160]}")
    raise TtsError(" | ".join(reasons))


def play_mp3_windows(path: str) -> bool:
    """Play an mp3 with Windows' built-in MCI player (no Qt multimedia, no codecs to install)."""
    import sys

    if sys.platform != "win32":
        return False
    import ctypes

    mci = ctypes.windll.winmm.mciSendStringW
    mci("close buddy", None, 0, 0)
    if mci(f'open "{path}" type mpegvideo alias buddy', None, 0, 0) != 0:
        return False
    ok = mci("play buddy wait", None, 0, 0) == 0
    mci("close buddy", None, 0, 0)
    return ok


class Speaker(QObject):
    """Text-to-speech. Natural neural voice (needs internet) -> Google voice -> offline system voice.
    Emits started/finished for the mouth animation, and `degraded` (with the real reason) whenever
    the natural voice could not be used, so a robotic voice is never a silent mystery."""

    started = pyqtSignal()
    finished = pyqtSignal()
    degraded = pyqtSignal(str)
    _ready = pyqtSignal(str, str)  # (mp3 path, spoken text), delivered on the UI thread

    def __init__(self, enabled: bool = True, gender: str = "male", voice: str = ""):
        super().__init__()
        self.enabled = enabled
        self.gender = gender
        self.voice = voice  # exact edge-tts voice name chosen with --voices / --set-voice ("" = automatic)
        self._player = None
        self._audio = None
        self._text = ""
        self._warned_reason = ""
        self._ready.connect(self._play)

    def say(self, text: str) -> None:
        text = clean_for_speech(text)
        if not self.enabled or not text:
            self.finished.emit()
            return
        self.stop()
        threading.Thread(target=self._synth, args=(text,), daemon=True).start()

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def _warn(self, reason: str) -> None:
        log(f"voice degraded: {reason}")
        if reason != self._warned_reason:  # tell the user once per distinct problem
            self._warned_reason = reason
            self.degraded.emit(f"Natural awaaz nahi chal payi. Wajah: {reason[:220]}")

    # -- online neural voice ---------------------------------------------------
    def _synth(self, text: str) -> None:
        try:
            path = synthesize(text, self.gender, self.voice)
        except TtsError as e:
            self._warn(str(e))
            self._fallback(text)
            return
        self._ready.emit(str(path), text)

    def _play(self, path: str, text: str) -> None:
        self._text = text
        try:
            from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

            if self._player is None:
                self._player = QMediaPlayer()
                self._audio = QAudioOutput()
                self._audio.setVolume(1.0)
                self._player.setAudioOutput(self._audio)
                self._player.mediaStatusChanged.connect(self._status)
                self._player.errorOccurred.connect(self._player_error)
            self._player.setSource(QUrl.fromLocalFile(path))
            self.started.emit()
            self._player.play()
        except Exception as e:  # QtMultimedia missing/broken
            log(f"QtMultimedia failed: {e!r}")
            threading.Thread(target=self._play_fallback, args=(path, text), daemon=True).start()

    def _status(self, status) -> None:
        from PyQt6.QtMultimedia import QMediaPlayer

        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.finished.emit()

    def _player_error(self, _err, message: str = "") -> None:
        log(f"QMediaPlayer error: {message}")
        path = self._player.source().toLocalFile() if self._player is not None else ""
        threading.Thread(target=self._play_fallback, args=(path, self._text), daemon=True).start()

    def _play_fallback(self, path: str, text: str) -> None:
        """Qt could not play the mp3: use Windows' own MCI player, else the offline voice."""
        self.started.emit()
        try:
            if path and play_mp3_windows(path):
                self.finished.emit()
                return
        except Exception as e:
            log(f"MCI failed: {e!r}")
        self._warn("mp3 play nahi ho paya (audio player problem)")
        self._fallback(text)

    # -- offline fallback ------------------------------------------------------
    def _fallback(self, text: str) -> None:
        self.started.emit()
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", 170)
            if DEVANAGARI.search(text):  # prefer an installed Hindi system voice
                for v in engine.getProperty("voices"):
                    if "hindi" in (v.name or "").lower() or "hi-in" in (v.id or "").lower():
                        engine.setProperty("voice", v.id)
                        break
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            log(f"pyttsx3 failed: {e!r}")  # no TTS engine at all: the bubble still shows the reply
        finally:
            self.finished.emit()
