"""Microphone listening (speech -> text) and realistic text-to-speech, off the UI thread."""

from __future__ import annotations

import asyncio
import re
import tempfile
import threading
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal

from . import providers

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


class Speaker(QObject):
    """Text-to-speech. Uses natural neural voices (edge-tts, needs internet) and falls back
    to the offline system voice (pyttsx3). Emits started/finished for the mouth animation."""

    started = pyqtSignal()
    finished = pyqtSignal()
    degraded = pyqtSignal(str)  # natural voice failed once; explains why the robotic fallback is used
    _ready = pyqtSignal(str)  # path of the synthesized mp3, delivered on the UI thread

    def __init__(self, enabled: bool = True, gender: str = "male"):
        super().__init__()
        self.enabled = enabled
        self.gender = gender
        self._player = None
        self._audio = None
        self._warned = False
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

    # -- neural voice -------------------------------------------------------
    def _synth(self, text: str) -> None:
        try:
            import edge_tts

            out = Path(tempfile.mkdtemp(prefix="buddy-tts-")) / "say.mp3"
            asyncio.run(edge_tts.Communicate(text, pick_voice(text, self.gender), rate="+4%").save(str(out)))
            self._ready.emit(str(out))
        except Exception as e:
            if not self._warned:
                self._warned = True
                why = "edge-tts install nahi hai (pip install edge-tts)" if isinstance(e, ImportError) else "internet/edge-tts problem"
                self.degraded.emit(f"Natural awaaz nahi chal payi ({why}), isliye system ki robotic awaaz use ho rahi hai.")
            self._fallback(text)

    def _play(self, path: str) -> None:
        try:
            from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

            if self._player is None:
                self._player = QMediaPlayer()
                self._audio = QAudioOutput()
                self._audio.setVolume(1.0)
                self._player.setAudioOutput(self._audio)
                self._player.mediaStatusChanged.connect(self._status)
                self._player.errorOccurred.connect(lambda *_: self.finished.emit())
            self._player.setSource(QUrl.fromLocalFile(path))
            self.started.emit()
            self._player.play()
        except Exception:
            self.finished.emit()

    def _status(self, status) -> None:
        from PyQt6.QtMultimedia import QMediaPlayer

        if status in (QMediaPlayer.MediaStatus.EndOfMedia, QMediaPlayer.MediaStatus.InvalidMedia):
            self.finished.emit()

    # -- offline fallback ---------------------------------------------------
    def _fallback(self, text: str) -> None:
        self.started.emit()
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", 175)
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass  # no TTS engine at all: the speech bubble still shows the reply
        finally:
            self.finished.emit()
