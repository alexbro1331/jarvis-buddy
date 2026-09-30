"""Microphone listening (speech -> text) and text-to-speech, off the UI thread."""

from __future__ import annotations

import threading

from PyQt6.QtCore import QObject, pyqtSignal

RATE = 16000


class Listener(QObject):
    """Records one utterance, then transcribes it. Emits `heard(text)` or `failed(msg)`."""

    heard = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, language: str = "en-IN"):
        super().__init__()
        self.language = language
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
                self.failed.emit("Kuch sunai nahi diya.")
                return
            import speech_recognition as sr

            data = sr.AudioData(audio, RATE, 2)
            try:
                text = sr.Recognizer().recognize_google(data, language=self.language)
            except sr.UnknownValueError:
                self.failed.emit("Samajh nahi aaya, dobara bolo.")
                return
            except sr.RequestError:
                self.failed.emit("Internet nahi hai, speech samajhne ke liye chahiye.")
                return
            self.heard.emit(text)
        except Exception as e:  # mic missing, driver error, ...
            self.failed.emit(f"Mic problem: {e}")
        finally:
            self._busy = False

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

        with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=block) as stream:
            while True:
                data, _ = stream.read(block)
                level = float(np.abs(data).mean())
                if threshold is None:
                    noise.append(level)
                    if len(noise) >= 4:  # first 0.4 s calibrates ambient noise
                        threshold = max(300.0, sum(noise) / len(noise) * 3)
                    continue
                if level > threshold:
                    started = True
                    silence = 0
                elif started:
                    silence += 1
                else:
                    waited += 1
                if started:
                    chunks.append(data.copy())
                if not started and waited > 60:  # 6 s of nothing
                    return None
                if started and (silence >= 10 or len(chunks) > 120):  # 1 s quiet / 12 s max
                    break
        return np.concatenate(chunks).tobytes() if chunks else None


class Speaker(QObject):
    """Text-to-speech via pyttsx3 (offline). Emits started/finished for mouth animation."""

    started = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, enabled: bool = True):
        super().__init__()
        self.enabled = enabled

    def say(self, text: str) -> None:
        if not self.enabled:
            self.finished.emit()
            return
        threading.Thread(target=self._run, args=(text,), daemon=True).start()

    def _run(self, text: str) -> None:
        self.started.emit()
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", 175)
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass  # no TTS engine: the speech bubble still shows the reply
        finally:
            self.finished.emit()
