import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from buddy import app as appmod
from buddy import voice
from buddy.config import Config


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def buddy(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    cfg = Config(tmp_path / "c.json")
    cfg["asked_key"] = cfg["asked_face"] = True
    b = appmod.BuddyApp(qapp, cfg)
    b.speaker.enabled = False
    monkeypatch.setattr(b.thinker, "think", lambda text: None)  # no network / threads here
    yield b
    b.quit = lambda: None


def test_what_you_said_stays_visible_above_the_reply(buddy):
    buddy.listener.heard.emit("youtube kholo")
    assert buddy.user_bubble.isVisible() and "youtube kholo" in buddy.user_bubble._text
    buddy.thinker.done.emit("YouTube खोल दिया!", False)
    assert buddy.bubble.isVisible() and "YouTube" in buddy.bubble._text
    assert buddy.user_bubble.isVisible()  # not replaced by the reply
    assert buddy.user_bubble.y() < buddy.bubble.y()  # stacked on top


def test_choose_face_without_a_face_shows_a_clear_message(buddy, tmp_path, monkeypatch):
    import cv2
    import numpy as np

    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), np.full((400, 400, 3), 200, np.uint8))
    monkeypatch.setattr(appmod.QFileDialog, "getOpenFileName", lambda *a, **k: (str(blank), ""))
    buddy.choose_face()
    assert "chehra nahi mila" in buddy.bubble._text


def test_voice_failure_is_explained_not_silent(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def boom(text, gender="male", voice_name=""):
        raise voice.TtsError("edge-tts: ClientConnectorError: blocked | gTTS: gTTSError: offline")

    monkeypatch.setattr(voice, "synthesize", boom)
    sp = voice.Speaker(True)
    msgs, done = [], []
    sp.degraded.connect(msgs.append)
    sp.finished.connect(lambda: done.append(1))
    sp._synth("नमस्ते")
    assert msgs and "blocked" in msgs[0] and done
    sp._synth("नमस्ते")  # same problem again -> not repeated
    assert len(msgs) == 1
    assert "blocked" in (Path(tmp_path) / "jarvis-buddy" / "buddy.log").read_text()


def test_synthesize_falls_back_to_gtts(monkeypatch):
    import types

    fake_edge = types.SimpleNamespace(Communicate=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("403")))
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge)

    class FakeG:
        def __init__(self, text, lang, tld):
            self.lang = lang

        def save(self, path):
            Path(path).write_bytes(b"x" * 1000)

    monkeypatch.setitem(sys.modules, "gtts", types.SimpleNamespace(gTTS=FakeG))
    assert voice.synthesize("नमस्ते").stat().st_size == 1000
