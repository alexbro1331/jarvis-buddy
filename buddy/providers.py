"""Free / cheap AI providers that speak the OpenAI-compatible chat API, plus speech-to-text.

Chat (brain):  Gemini (free tier), Groq (free tier), Ollama (runs on your own PC, unlimited).
Speech-to-text: Groq Whisper (free tier, very good at Hindi/Hinglish) or faster-whisper on your own PC.

Free-tier limits and model names change often, so nothing here is hard-wired: models come from
config (`<provider>_model`), and if a model name is rejected we ask the provider for its model list
and pick the closest match.
"""

from __future__ import annotations

import io
import json
import wave

import requests

TIMEOUT = 45

PROVIDERS = {
    "gemini": {
        "label": "Gemini (free)",
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key": "gemini_api_key",
        "model": "gemini-3.5-flash-lite",
        "prefer": ("flash-lite", "flash"),
        "avoid": ("tts", "image", "embedding", "live", "audio", "robotics", "thinking"),
        "extra": {},
        "signup": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "label": "Groq (free)",
        "base": "https://api.groq.com/openai/v1",
        "key": "groq_api_key",
        "model": "openai/gpt-oss-120b",
        "prefer": ("gpt-oss-120b", "gpt-oss-20b", "llama"),
        "avoid": ("whisper", "tts", "guard", "distil"),
        "extra": {"reasoning_effort": "low"},
        "signup": "https://console.groq.com/keys",
    },
    "ollama": {
        "label": "Ollama (on this PC, offline)",
        "base": "http://localhost:11434/v1",
        "key": None,
        "model": "qwen3:8b",
        "prefer": ("qwen3", "qwen2.5", "llama3", "gemma"),
        "avoid": ("embed",),
        "extra": {},
        "signup": "https://ollama.com/download",
    },
}


class ProviderError(Exception):
    """Base class. Subclasses tell the brain whether to try the next provider."""


class RateLimited(ProviderError):
    pass


class AuthFailed(ProviderError):
    pass


class Unavailable(ProviderError):
    pass


def base_url(cfg, name: str) -> str:
    return (cfg.data.get(f"{name}_base_url") or PROVIDERS[name]["base"]).rstrip("/")


def api_key(cfg, name: str) -> str | None:
    field = PROVIDERS[name]["key"]
    return (cfg.data.get(field) or "").strip() or None if field else None


def configured(cfg, name: str) -> bool:
    """A provider is usable when it has a key (Ollama needs `use_ollama` switched on instead)."""
    if name == "ollama":
        return bool(cfg.data.get("use_ollama"))
    return api_key(cfg, name) is not None


def _headers(cfg, name: str) -> dict:
    key = api_key(cfg, name)
    return {"Authorization": f"Bearer {key}"} if key else {}


def _check(resp: requests.Response, name: str) -> None:
    if resp.status_code == 429:
        raise RateLimited(f"{name}: rate limit")
    if resp.status_code in (401, 403):
        raise AuthFailed(f"{name}: key rejected ({resp.status_code})")
    if resp.status_code >= 500:
        raise Unavailable(f"{name}: server error {resp.status_code}")


def list_models(cfg, name: str) -> list[str]:
    try:
        r = requests.get(base_url(cfg, name) + "/models", headers=_headers(cfg, name), timeout=TIMEOUT)
    except requests.RequestException as e:
        raise Unavailable(f"{name}: {e}") from e
    _check(r, name)
    r.raise_for_status()
    return [m["id"].removeprefix("models/") for m in r.json().get("data", [])]


def pick_model(ids: list[str], spec: dict) -> str | None:
    usable = [i for i in ids if not any(bad in i.lower() for bad in spec["avoid"])]
    for want in spec["prefer"]:
        hits = sorted(i for i in usable if want in i.lower())
        if hits:
            return hits[-1]  # highest version sorts last
    return usable[0] if usable else None


def chat(cfg, name: str, messages: list[dict], tools: list[dict] | None) -> dict:
    """One chat-completions call. Returns the assistant message dict (may contain tool_calls)."""
    spec = PROVIDERS[name]
    model = cfg.data.get(f"{name}_model") or spec["model"]
    for attempt in (1, 2):
        body = {"model": model, "messages": messages, **spec["extra"]}
        if tools:
            body["tools"] = tools
        try:
            r = requests.post(
                base_url(cfg, name) + "/chat/completions", json=body, headers=_headers(cfg, name), timeout=TIMEOUT
            )
        except requests.RequestException as e:
            raise Unavailable(f"{name}: {e}") from e
        if r.status_code in (400, 404) and attempt == 1 and "model" in r.text.lower():
            # model name retired/renamed: ask the provider what it has now and remember the choice
            found = pick_model(list_models(cfg, name), spec)
            if found and found != model:
                model = found
                cfg[f"{name}_model"] = found
                cfg.save()
                continue
        _check(r, name)
        if r.status_code != 200:
            raise Unavailable(f"{name}: HTTP {r.status_code} {r.text[:200]}")
        return r.json()["choices"][0]["message"]
    raise Unavailable(f"{name}: no working model")


def to_openai_tools(tools: list[dict]) -> list[dict]:
    """Convert the Anthropic-style tool list (name/description/input_schema) to OpenAI format."""
    return [
        {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in tools
    ]


# ---------------------------------------------------------------- speech to text

# Whisper sometimes "hears" these in near-silence; never treat them as a command.
WHISPER_GHOSTS = {"thank you", "thanks for watching", "thank you for watching", "you", "bye", "."}


def wav_bytes(pcm: bytes, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def transcribe_groq(cfg, pcm: bytes, rate: int = 16000) -> str:
    """Groq-hosted Whisper. Free tier allows hours of audio per day."""
    if not api_key(cfg, "groq"):
        raise AuthFailed("groq: no key")
    data = {
        "model": cfg.data.get("groq_stt_model") or "whisper-large-v3-turbo",
        "response_format": "json",
        "temperature": "0",
        # nudges Whisper towards the vocabulary an assistant hears, and towards Hindi+English mixing
        "prompt": f"{cfg['user_name']} talking to {cfg['name']}, a voice assistant. Hindi and English mixed. "
                  "YouTube, Google, folder, open, search, timer.",
    }
    lang = cfg.data.get("stt_language")  # e.g. "hi" or "en"; empty = auto-detect
    if lang:
        data["language"] = lang
    try:
        r = requests.post(
            base_url(cfg, "groq") + "/audio/transcriptions",
            headers=_headers(cfg, "groq"),
            data=data,
            files={"file": ("speech.wav", wav_bytes(pcm, rate), "audio/wav")},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise Unavailable(f"groq stt: {e}") from e
    _check(r, "groq stt")
    if r.status_code != 200:
        raise Unavailable(f"groq stt: HTTP {r.status_code} {r.text[:200]}")
    text = (r.json().get("text") or "").strip()
    return "" if text.lower().strip(" .!") in WHISPER_GHOSTS else text


_local_model = None


def transcribe_local(cfg, pcm: bytes) -> str:
    """faster-whisper on this PC: free, unlimited, offline (downloads the model on first use)."""
    global _local_model
    import numpy as np

    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise Unavailable("faster-whisper is not installed (pip install faster-whisper)") from e
    if _local_model is None:
        _local_model = WhisperModel(cfg.data.get("local_stt_model") or "small", device="cpu", compute_type="int8")
    audio = np.frombuffer(pcm, dtype=np.int16).astype("float32") / 32768.0
    segments, _info = _local_model.transcribe(
        audio, language=cfg.data.get("stt_language") or None, vad_filter=True, beam_size=1, temperature=0
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    return "" if text.lower().strip(" .!") in WHISPER_GHOSTS else text


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
