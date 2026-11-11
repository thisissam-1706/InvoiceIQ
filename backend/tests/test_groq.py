"""GroqClient retry/fallback behaviour against a fake OpenAI-compatible client (no network)."""

import base64
import io
from types import SimpleNamespace as NS

import httpx
import openai
import pytest
from PIL import Image

from backend.app.llm import groq as groq_mod
from backend.app.llm.base import LLMError, LLMTransientError
from backend.app.llm.groq import GroqClient


def _status_error(code: int, message: str = "error", headers: dict | None = None) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(code, request=request, headers=headers or {}, json={"error": {"message": message}})
    return openai.APIStatusError(message, response=response, body={"error": {"message": message}})


class FakeCompletions:
    def __init__(self, script):
        self.script = script  # model -> list of results (Exception or str), consumed in order
        self.calls = []

    def create(self, model, messages, **kwargs):
        self.calls.append((model, kwargs, messages))
        queue = self.script.get(model, [])
        result = queue.pop(0) if queue else _status_error(404, f"The model `{model}` does not exist")
        if isinstance(result, Exception):
            raise result
        return NS(choices=[NS(message=NS(content=result))])


def make_client(script, models=(), model="qwen/qwen3.6-27b"):
    c = GroqClient.__new__(GroqClient)
    completions = FakeCompletions(script)
    c._client = NS(chat=NS(completions=completions), models=NS(list=lambda: [NS(id=m) for m in models]))
    c.model = model
    c._dropped = set()
    return c, completions


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    waits = []
    monkeypatch.setattr(groq_mod.time, "sleep", lambda s: waits.append(s))
    return waits


def test_success_sends_json_mode_and_hides_reasoning():
    c, comp = make_client({"qwen/qwen3.6-27b": ['{"ok": true}']})
    assert c.extract("text", None, "prompt", None) == {"ok": True}
    _, kwargs, _ = comp.calls[0]
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0
    assert kwargs["extra_body"] == {"reasoning_format": "hidden"}


def test_scanned_page_is_sent_as_jpeg():
    c, comp = make_client({"qwen/qwen3.6-27b": ['{"ok": 1}']})
    c.extract(None, [_png()], "prompt", None)
    url = comp.calls[0][2][0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(url.split(",", 1)[1])[:3] == b"\xff\xd8\xff"


def test_think_tags_are_stripped():
    c, _ = make_client({"qwen/qwen3.6-27b": ['<think>let me see</think>\n{"a": 1}']})
    assert c.extract("t", None, "p", None) == {"a": 1}


def test_rejected_reasoning_format_is_dropped():
    c, comp = make_client({"qwen/qwen3.6-27b": [_status_error(400, "reasoning_format is not supported with this model"), "ok"]})
    assert c.generate_text("p") == "ok"
    assert "extra_body" not in comp.calls[1][1]


def test_503_twice_then_success_same_model(no_sleep):
    c, comp = make_client({"qwen/qwen3.6-27b": [_status_error(503), _status_error(503), "hello"]})
    assert c.generate_text("p") == "hello"
    assert [m for m, _, _ in comp.calls] == ["qwen/qwen3.6-27b"] * 3
    assert len(no_sleep) == 2


def test_text_request_can_fall_back_to_text_only_model():
    busy = {m: [_status_error(503)] * 3 for m in groq_mod.VISION_FALLBACKS}
    c, comp = make_client({**busy, "llama-3.3-70b-versatile": ["text ok"]})
    assert c.generate_text("p") == "text ok"


def test_image_request_never_uses_text_only_models():
    busy = {m: [_status_error(503)] * 3 for m in groq_mod.VISION_FALLBACKS}
    c, comp = make_client({**busy, "llama-3.3-70b-versatile": ["should not be used"]},
                          models=["llama-3.3-70b-versatile", "whisper-large-v3"])
    with pytest.raises(LLMTransientError):
        c.extract(None, [_png()], "p", None)
    used = {m for m, _, _ in comp.calls}
    assert "llama-3.3-70b-versatile" not in used and "whisper-large-v3" not in used


def test_retired_model_falls_back_to_next():
    c, _ = make_client({"qwen/qwen3.8-27b": ["hi"]}, model="qwen/qwen3.6-27b")  # 3.6 -> 404
    assert c.generate_text("p") == "hi"


def test_429_uses_retry_after_header_capped(no_sleep):
    c, _ = make_client({"qwen/qwen3.6-27b": [_status_error(429, headers={"retry-after": "45"}), "ok"]})
    assert c.generate_text("p") == "ok"
    assert no_sleep == [groq_mod.MAX_RETRY_DELAY]


def test_auth_error_is_not_retried():
    c, comp = make_client({"qwen/qwen3.6-27b": [_status_error(401, "Invalid API Key")]})
    with pytest.raises(LLMError) as info:
        c.generate_text("p")
    assert not isinstance(info.value, LLMTransientError)
    assert len(comp.calls) == 1


def test_settings_default_and_model_mismatch(monkeypatch):
    from backend.app.settings import load_env

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_MODEL", "gemini-3.8-flash")  # left over from a Gemini setup
    env = load_env()
    assert env.llm_provider == "groq"
    assert env.llm_model == "qwen/qwen3.6-27b"
