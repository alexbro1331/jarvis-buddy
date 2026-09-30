import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from buddy import brain, providers
from buddy.config import Config


class Mock:
    """A tiny OpenAI-compatible server: scripted /chat/completions, /models and /audio/transcriptions."""

    def __init__(self):
        self.chat_script = []  # list of (status, body)
        self.requests = []
        self.models = []
        self.transcript = "youtube kholo"
        mock = self

        class H(BaseHTTPRequestHandler):
            def _send(self, status, body):
                out = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def do_GET(self):
                mock.requests.append(("GET", self.path, None, dict(self.headers)))
                self._send(200, {"data": [{"id": m} for m in mock.models]})

            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                if self.path.endswith("/audio/transcriptions"):
                    mock.requests.append(("POST", self.path, raw, dict(self.headers)))
                    return self._send(200, {"text": mock.transcript})
                body = json.loads(raw)
                mock.requests.append(("POST", self.path, body, dict(self.headers)))
                status, payload = mock.chat_script.pop(0)
                self._send(status, payload)

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def close(self):
        self.srv.shutdown()


def reply(text):
    return 200, {"choices": [{"message": {"role": "assistant", "content": text}}]}


def tool_call(tool, **args):
    return 200, {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}]}}]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "Desktop").mkdir()
    a, b = Mock(), Mock()
    cfg = Config(tmp_path / "config.json")
    cfg.data.update(gemini_api_key="g-key", groq_api_key="gsk-key", gemini_base_url=a.url, groq_base_url=b.url)
    yield types.SimpleNamespace(cfg=cfg, gemini=a, groq=b, home=tmp_path)
    a.close()
    b.close()


def test_gemini_tool_loop(env):
    env.gemini.chat_script = [tool_call("create_folder", name="Chandan"), reply("फ़ोल्डर बन गया!")]
    b = brain.Brain(env.cfg)
    assert b.ask("chandan naam ka folder banao") == "फ़ोल्डर बन गया!"
    assert (env.home / "Desktop" / "Chandan").is_dir()
    first = env.gemini.requests[0]
    assert first[3]["Authorization"] == "Bearer g-key"
    assert first[2]["tools"][0]["type"] == "function" and first[2]["model"].startswith("gemini")
    # the tool result went back to the model in OpenAI format
    tool_msg = env.gemini.requests[1][2]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"
    assert b.last_provider == "gemini"


def test_groq_request_uses_low_reasoning(env):
    env.cfg.data["gemini_api_key"] = ""
    env.groq.chat_script = [reply("ok")]
    brain.Brain(env.cfg).ask("hi")
    assert env.groq.requests[0][2]["reasoning_effort"] == "low"


def test_rate_limit_falls_back_to_next_provider(env):
    env.gemini.chat_script = [(429, {"error": {"message": "quota"}})]
    env.groq.chat_script = [reply("Groq ने जवाब दिया")]
    b = brain.Brain(env.cfg)
    assert b.ask("hello") == "Groq ने जवाब दिया"
    assert b.last_provider == "groq"


def test_all_providers_limited_gives_friendly_message(env):
    env.gemini.chat_script = [(429, {})]
    env.groq.chat_script = [(429, {})]
    assert "limit" in brain.Brain(env.cfg).ask("hello")


def test_no_fallback_after_an_action_already_ran(env):
    env.gemini.chat_script = [tool_call("create_folder", name="Once"), (500, {})]
    env.groq.chat_script = [reply("should never be used")]
    b = brain.Brain(env.cfg)
    b.ask("make folder once")
    assert env.groq.requests == []  # the folder action must not be repeated elsewhere


def test_bad_key_is_reported(env):
    env.gemini.chat_script = [(401, {})]
    env.groq.chat_script = [(403, {})]
    assert "key" in brain.Brain(env.cfg).ask("hello")


def test_retired_model_is_rediscovered(env):
    env.cfg["gemini_model"] = "gemini-2.0-flash-lite"  # pretend this name was retired
    env.gemini.chat_script = [(404, {"error": {"message": "model not found"}}), reply("mil gaya")]
    env.gemini.models = ["models/gemini-3.5-flash-lite", "models/gemini-3.5-pro", "models/text-embedding-9"]
    assert brain.Brain(env.cfg).ask("hi") == "mil gaya"
    assert env.cfg["gemini_model"] == "gemini-3.5-flash-lite"
    assert env.gemini.requests[-1][2]["model"] == "gemini-3.5-flash-lite"


def test_pick_model_prefers_flash_lite_and_skips_tts():
    spec = providers.PROVIDERS["gemini"]
    ids = ["gemini-3.5-flash-preview-tts", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]
    assert providers.pick_model(ids, spec) == "gemini-3.5-flash-lite"


def test_think_tags_stripped(env):
    env.gemini.chat_script = [reply("<think>hmm</think>नमस्ते!")]
    assert brain.Brain(env.cfg).ask("hi") == "नमस्ते!"


def test_groq_whisper(env):
    from buddy.voice import Listener

    env.groq.transcript = "  YouTube खोलो "
    pcm = b"\x00\x01" * 1600
    assert providers.transcribe_groq(env.cfg, pcm) == "YouTube खोलो"
    req = env.groq.requests[0]
    assert b"whisper-large-v3-turbo" in req[2] and b"RIFF" in req[2]  # model field + a real WAV upload
    assert Listener("en-IN", env.cfg).engine() == "groq"  # auto picks Groq when a key exists
    env.groq.transcript = "Thank you."
    assert providers.transcribe_groq(env.cfg, pcm) == ""  # Whisper's silence hallucination is dropped


def test_listener_falls_back_to_google_when_groq_limited(env, monkeypatch):
    from buddy.voice import Listener

    def limited(*a, **k):
        raise providers.RateLimited("groq")

    monkeypatch.setattr(providers, "transcribe_groq", limited)
    lst = Listener("en-IN", env.cfg)
    monkeypatch.setattr(lst, "_transcribe_google", lambda pcm: "from google")
    assert lst._transcribe(b"\x00\x00") == "from google"
    env.cfg["stt_engine"] = "google"
    assert lst.engine() == "google"


def test_local_whisper(env, monkeypatch):
    seg = types.SimpleNamespace(text=" नमस्ते बडी ")

    class FakeModel:
        def __init__(self, size, **kw):
            self.size = size

        def transcribe(self, audio, **kw):
            assert audio.dtype.name == "float32"
            return [seg], None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    monkeypatch.setattr(providers, "_local_model", None)
    assert providers.transcribe_local(env.cfg, b"\x00\x01" * 800) == "नमस्ते बडी"
