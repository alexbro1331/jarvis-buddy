import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from buddy import app, voice


def cfg_file(tmp_path):
    return json.loads((tmp_path / "jarvis-buddy" / "config.json").read_text(encoding="utf-8"))


def test_set_key_saves_and_is_seen_by_providers(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert app.main(["--set-key", "groq", "  gsk_abc123  "]) == 0
    assert app.main(["--set-key", "gemini", "AIza-xyz"]) == 0
    saved = cfg_file(tmp_path)
    assert saved["groq_api_key"] == "gsk_abc123" and saved["gemini_api_key"] == "AIza-xyz"
    assert "Saved groq key (10 characters)" in capsys.readouterr().out
    from buddy import brain
    from buddy.config import Config

    assert brain.usable_providers(Config()) == ["gemini", "groq"]


def test_set_key_rejects_unknown_service(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert app.main(["--set-key", "openai", "x"]) == 1


def test_set_voice_and_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app.main(["--set-voice", "en-US-AvaMultilingualNeural"])
    assert cfg_file(tmp_path)["voice_name"] == "en-US-AvaMultilingualNeural"
    app.main(["--set-voice", "auto"])
    assert cfg_file(tmp_path)["voice_name"] == ""


def test_chosen_voice_is_used_for_synthesis(monkeypatch):
    import types

    used = {}

    class Fake:
        def __init__(self, text, voice, rate):
            used["voice"] = voice

        async def save(self, path):
            Path(path).write_bytes(b"x" * 1000)

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=Fake))
    voice.synthesize("नमस्ते", voice="en-US-AvaMultilingualNeural")
    assert used["voice"] == "en-US-AvaMultilingualNeural"
    voice.synthesize("नमस्ते")
    assert used["voice"] == "hi-IN-MadhurNeural"
