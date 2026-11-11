"""Busy-model handling: retry, model chain, offline fallback. The genai client is mocked; no network."""
import json

import pytest
from google.genai import errors
from sqlmodel import select

from backend.app import db
from backend.app.llm import ResolvedClient
from backend.app.llm import gemini as gemini_mod
from backend.app.llm.base import LLMTransientError
from backend.app.llm.cache import ResponseCache
from backend.app.llm.gemini import GeminiClient
from backend.app.models import Run
from backend.app.pipeline import ingest, llm_extract
from backend.app.pipeline.orchestrator import create_run, process_run
from backend.app.settings import SAMPLES_DIR
from backend.scripts.generate_samples import EXPECTED
from backend.scripts.generate_samples import main as generate_samples

OK_JSON = json.dumps({"line_items": []})


def err503():
    return errors.ServerError(503, {"error": {"code": 503, "message": "model is currently experiencing high demand", "status": "UNAVAILABLE"}})


def err429(delay="13s"):
    return errors.ClientError(
        429,
        {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED",
                   "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}},
    )


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, behaviour):
        self.behaviour = behaviour  # model -> list of outcomes (exception or text); last repeats
        self.calls: list[str] = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        outcomes = self.behaviour[model]
        outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    def list(self):
        return []


class FakeGenaiClient:
    behaviour: dict = {}

    def __init__(self, api_key=None):
        self.models = FakeModels(FakeGenaiClient.behaviour)


@pytest.fixture
def sleeps(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(gemini_mod.time, "sleep", waits.append)
    monkeypatch.setattr(gemini_mod.random, "uniform", lambda a, b: 0.0)
    return waits


def make_client(monkeypatch, behaviour, model="model-a"):
    """Models not listed in `behaviour` answer 503 forever."""
    from collections import defaultdict

    full = defaultdict(lambda: [err503()], behaviour)
    FakeGenaiClient.behaviour = full
    import google.genai as genai

    monkeypatch.setattr(genai, "Client", FakeGenaiClient)
    return GeminiClient("key", model)


def test_503_twice_then_success_same_model(monkeypatch, sleeps):
    client = make_client(monkeypatch, {"model-a": [err503(), err503(), OK_JSON]})
    assert client.generate_text("hi") == OK_JSON
    assert client._client.models.calls == ["model-a"] * 3
    assert client.model == "model-a"
    assert sleeps == [2.0, 6.0]


def test_all_attempts_fail_on_a_then_success_on_b(monkeypatch, sleeps):
    monkeypatch.setattr(gemini_mod, "FLASH_FALLBACKS", ["model-b"])
    client = make_client(monkeypatch, {"model-a": [err503()], "model-b": [OK_JSON]})
    assert client.generate_text("hi") == OK_JSON
    assert client._client.models.calls == ["model-a"] * 3 + ["model-b"]
    assert client.model == "model-b"


def test_every_model_fails_raises_transient_error(monkeypatch, sleeps):
    monkeypatch.setattr(gemini_mod, "FLASH_FALLBACKS", ["model-b"])
    client = make_client(monkeypatch, {})
    with pytest.raises(LLMTransientError) as info:
        client.generate_text("hi")
    assert "model-a" in str(info.value) and "model-b" in str(info.value) and "503" in str(info.value)
    assert info.value.status_code == 503


def test_429_uses_retry_delay_capped(monkeypatch, sleeps):
    client = make_client(monkeypatch, {"model-a": [err429("13s"), err429("90s"), OK_JSON]})
    assert client.generate_text("hi") == OK_JSON
    assert sleeps == [13.0, 20.0]


# ---- pipeline level ----

@pytest.fixture
def env(fresh_db, tmp_path, monkeypatch, sleeps):
    if not all((SAMPLES_DIR / n).exists() for n in EXPECTED):
        generate_samples()
    monkeypatch.setattr(ingest, "UPLOADS_DIR", tmp_path / "uploads")
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(llm_extract, "ResponseCache", lambda: ResponseCache(cache_dir))
    monkeypatch.setattr(gemini_mod, "FLASH_FALLBACKS", ["model-b"])
    return cache_dir


def run_sample(monkeypatch, name):
    client = make_client(monkeypatch, {})
    run = create_run(SAMPLES_DIR / name, name, "batch")
    process_run(run.id, stage_delay_ms=0, resolved=ResolvedClient(client))
    with db.session() as s:
        return s.get(Run, run.id)


def test_digital_pdf_falls_back_to_offline_and_is_held(env, monkeypatch):
    run = run_sample(monkeypatch, "01_acme_clean.pdf")
    assert run.status == "completed" and run.decision == "HOLD"
    codes = {f["code"] for f in json.loads(run.rules_json)["findings"]}
    assert "LLM_FALLBACK_OFFLINE" in codes
    meta = json.loads(run.extraction_json)["meta"]
    assert meta["provider"] == "offline"
    assert meta["fallback_from"] == "gemini/model-a"
    assert meta["fallback_reason"].startswith("503")
    assert ResponseCache(env).count() == 0


def test_scanned_pdf_fails_with_overloaded_message(env, monkeypatch):
    run = run_sample(monkeypatch, "07_delta_scanned_no_po.pdf")
    assert run.status == "failed" and run.decision is None
    assert run.error_message == "The AI model is overloaded right now (503). Use Re-run in a minute."
    assert ResponseCache(env).count() == 0
