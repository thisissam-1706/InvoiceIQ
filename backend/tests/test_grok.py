"""GrokClient retry/fallback behaviour against a fake OpenAI-compatible client (no network)."""

from types import SimpleNamespace as NS

import httpx
import openai
import pytest

from backend.app.llm import grok as grok_mod
from backend.app.llm.base import LLMError, LLMTransientError
from backend.app.llm.grok import GrokClient


def _status_error(code: int, message: str = "error", headers: dict | None = None) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.x.ai/v1/chat/completions")
    response = httpx.Response(code, request=request, headers=headers or {}, json={"error": {"message": message}})
    return openai.APIStatusError(message, response=response, body={"error": {"message": message}})


class FakeCompletions:
    def __init__(self, script):
        self.script = script  # model -> list of results (Exception or str), consumed in order
        self.calls = []

    def create(self, model, messages, **kwargs):
        self.calls.append((model, kwargs))
        queue = self.script.get(model, [])
        result = queue.pop(0) if queue else _status_error(404, f"model {model} not found")
        if isinstance(result, Exception):
            raise result
        return NS(choices=[NS(message=NS(content=result))])


def make_client(script, models=()):
    c = GrokClient.__new__(GrokClient)
    completions = FakeCompletions(script)
    c._client = NS(chat=NS(completions=completions), models=NS(list=lambda: [NS(id=m) for m in models]))
    c.model = "grok-4.3"
    c._use_temperature = True
    c._use_json_format = True
    return c, completions


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    waits = []
    monkeypatch.setattr(grok_mod.time, "sleep", lambda s: waits.append(s))
    return waits


def test_success_first_try():
    c, comp = make_client({"grok-4.3": ['{"ok": true}']})
    assert c.extract("text", None, "prompt", None) == {"ok": True}
    assert comp.calls[0][1]["response_format"] == {"type": "json_object"}
    assert comp.calls[0][1]["temperature"] == 0


def test_503_twice_then_success_same_model(no_sleep):
    c, comp = make_client({"grok-4.3": [_status_error(503), _status_error(503), "hello"]})
    assert c.generate_text("p") == "hello"
    assert [m for m, _ in comp.calls] == ["grok-4.3"] * 3
    assert len(no_sleep) == 2


def test_retired_model_falls_back_to_next():
    c, comp = make_client({"grok-4.5": ["hi"]})  # grok-4.3 -> 404
    c.model = "grok-4.3"
    assert c.generate_text("p") == "hi"
    assert c.model == "grok-4.5"


def test_every_model_overloaded_raises_transient():
    script = {m: [_status_error(503)] * 3 for m in ["grok-4.3", "grok-4.5", "grok-4", "grok-5"]}
    c, comp = make_client(script, models=["grok-5", "grok-imagine-image"])
    with pytest.raises(LLMTransientError) as info:
        c.generate_text("p")
    assert info.value.status_code == 503
    assert "grok-5" in str(info.value)  # discovered model was tried
    assert all("imagine" not in m for m, _ in comp.calls)


def test_429_uses_retry_after_header_capped(no_sleep):
    c, _ = make_client({"grok-4.3": [_status_error(429, headers={"retry-after": "45"}), "ok"]})
    assert c.generate_text("p") == "ok"
    assert no_sleep == [grok_mod.MAX_RETRY_DELAY]


def test_temperature_rejected_is_dropped():
    c, comp = make_client({"grok-4.3": [_status_error(400, "temperature is not supported for this model"), "ok"]})
    assert c.generate_text("p") == "ok"
    assert "temperature" not in comp.calls[1][1]


def test_auth_error_is_not_retried():
    c, comp = make_client({"grok-4.3": [_status_error(401, "invalid api key")]})
    with pytest.raises(LLMError) as info:
        c.generate_text("p")
    assert not isinstance(info.value, LLMTransientError)
    assert len(comp.calls) == 1


def test_fenced_json_is_accepted():
    c, _ = make_client({"grok-4.3": ['```json\n{"a": 1}\n```']})
    assert c.extract("t", None, "p", None) == {"a": 1}


def test_settings_default_and_model_mismatch(monkeypatch):
    from backend.app.settings import load_env

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_MODEL", "gemini-3.8-flash")  # left over from a Gemini setup
    env = load_env()
    assert env.llm_provider == "grok"
    assert env.llm_model == "grok-4.3"
