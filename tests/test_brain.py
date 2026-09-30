import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from buddy import brain
from buddy.config import Config
from buddy.voice import pick_voice


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "Desktop").mkdir()
    c = Config(tmp_path / "config.json")
    c["anthropic_api_key"] = "sk-test"  # these tests drive the Claude path with a fake client
    c["brain_order"] = ["claude"]
    return c


class FakeClient:
    """Plays back scripted responses and records the requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})
        return self.responses.pop(0)


def text(t):
    return NS(stop_reason="end_turn", content=[NS(type="text", text=t)])


def tool(tool_name, **args):
    return NS(stop_reason="tool_use", content=[NS(type="tool_use", id="t1", name=tool_name, input=args)])


def test_plain_answer_and_memory(cfg):
    c = FakeClient(text("Paris hai!"), text("Dobara Paris!"))
    b = brain.Brain(cfg, client=c)
    assert b.ask("capital of france?") == "Paris hai!"
    b.ask("aur?")
    # second request carries the first exchange
    msgs = c.requests[1]["messages"]
    assert msgs[0] == {"role": "user", "content": "capital of france?"}
    assert msgs[1] == {"role": "assistant", "content": "Paris hai!"}
    req = c.requests[0]
    assert req["model"] == "claude-opus-5-5" and req["output_config"] == {"effort": "low"}
    assert req["fallbacks"] == "default" and "Chandan" in req["system"]


def test_tool_loop_creates_folder(cfg, tmp_path):
    c = FakeClient(tool("create_folder", name="Chandan"), text("Folder ban gaya!"))
    b = brain.Brain(cfg, client=c)
    assert b.ask("ek folder banao chandan naam ka") == "Folder ban gaya!"
    assert (tmp_path / "Desktop" / "Chandan").is_dir()
    result = c.requests[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "t1"


def test_timer_and_notes(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("buddy.brain.config_dir", lambda: tmp_path)
    fired = []
    c = FakeClient(tool("set_timer", minutes=5, label="chai"), text("Ho gaya"))
    b = brain.Brain(cfg, on_timer=lambda m, l: fired.append((m, l)), client=c)
    b.notes = brain.Notes(tmp_path / "n.json")
    b.tools.notes = b.notes
    b.ask("5 minute baad chai yaad dilana")
    assert fired == [(5.0, "chai")]
    b.tools.run("remember", {"note": "Chandan likes chai"})
    assert "chai" in b.notes.text()


def test_bad_tool_input_is_reported_not_raised(cfg):
    tb = brain.Toolbox(cfg, brain.Notes(Path("/nonexistent/n.json")))
    assert tb.run("create_folder", {}).startswith("Bad arguments")
    assert tb.run("nope", {}).startswith("Unknown tool")
    assert "Invalid" in tb.run("create_folder", {"name": "///"})


def test_refusal(cfg):
    c = FakeClient(NS(stop_reason="refusal", content=[]))
    assert "मदद नहीं" in brain.Brain(cfg, client=c).ask("x")


def test_provider_availability(cfg, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg["anthropic_api_key"] = ""
    cfg["brain_order"] = ["gemini", "groq", "ollama", "claude"]
    assert not brain.available(cfg)
    cfg["groq_api_key"] = "gsk-x"
    assert brain.usable_providers(cfg) == ["groq"]
    cfg["gemini_api_key"] = "g-x"
    cfg["use_ollama"] = True
    cfg["anthropic_api_key"] = "sk-x"
    assert brain.usable_providers(cfg) == ["gemini", "groq", "ollama", "claude"]


def test_voice_choice():
    assert pick_voice("Namaste Chandan") == "en-IN-PrabhatNeural"
    assert pick_voice("नमस्ते चंदन") == "hi-IN-MadhurNeural"
    assert pick_voice("hello", "female") == "en-IN-NeerjaNeural"
