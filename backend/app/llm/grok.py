"""xAI Grok via its OpenAI-compatible API (https://api.x.ai/v1)."""

import base64
import json
import logging
import random
import re
import time
from typing import Optional

from .base import LLMError, LLMTransientError

log = logging.getLogger(__name__)

XAI_BASE_URL = "https://api.x.ai/v1"
TRANSIENT_CODES = {429, 500, 502, 503, 504}
BACKOFF_SECONDS = [2.0, 6.0]  # waits before retry 1 and retry 2 on the same model
MAX_RETRY_DELAY = 20.0
# Tried in order after the configured model if it is retired (404) or keeps failing.
GROK_FALLBACKS = ["grok-4.3", "grok-4.5", "grok-4"]
# Model names that are not text/vision chat models.
_SKIP = ("image", "imagine", "video", "audio", "tts", "embed", "build")


def _rank(name: str) -> tuple:
    """Sort key: non-preview first, then newest version."""
    m = re.search(r"grok-(\d+(?:\.\d+)?)", name)
    version = float(m.group(1)) if m else 0.0
    return ("preview" not in name and "beta" not in name, version)


class GrokClient:
    provider = "grok"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise LLMError("XAI_API_KEY is empty. Add it to .env or set LLM_PROVIDER=offline.")
        from openai import OpenAI

        # No request timeout (timeout=None) and no SDK-level retries: retries are handled below.
        self._client = OpenAI(api_key=api_key, base_url=XAI_BASE_URL, timeout=None, max_retries=0)
        self.model = model
        self._use_temperature = True
        self._use_json_format = True

    @staticmethod
    def _retry_after(exc) -> Optional[float]:
        response = getattr(exc, "response", None)
        value = response.headers.get("retry-after") if response is not None else None
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None

    def _call_model(self, model: str, content, json_mode: bool, remaining: list[str]) -> Optional[str]:
        """Call one model, retrying transient errors. Returns text, or None to move on to the next model."""
        import openai

        attempt = 0
        while True:
            kwargs = {}
            if self._use_temperature:
                kwargs["temperature"] = 0
            if json_mode and self._use_json_format:
                kwargs["response_format"] = {"type": "json_object"}
            try:
                response = self._client.chat.completions.create(
                    model=model, messages=[{"role": "user", "content": content}], **kwargs
                )
                text = response.choices[0].message.content
                if not text:
                    raise LLMError("Grok returned an empty response")
                return text
            except openai.APIStatusError as exc:
                code = exc.status_code
                message = str(getattr(exc, "message", "") or exc)
                if code == 400 and "temperature" in message.lower() and self._use_temperature:
                    log.warning("Grok %s rejected temperature; retrying without it", model)
                    self._use_temperature = False
                    continue
                if code == 400 and "response_format" in message.lower() and self._use_json_format:
                    log.warning("Grok %s rejected response_format; retrying without it", model)
                    self._use_json_format = False
                    continue
                if code == 404 or (code == 400 and "model" in message.lower() and "not" in message.lower()):
                    self._last_error = exc
                    return None
                if code not in TRANSIENT_CODES:
                    raise LLMError(f"Grok request failed ({code}): {message}") from exc
                self._last_error = self._last_transient = exc
            except openai.APIConnectionError as exc:
                code = None
                self._last_error = self._last_transient = exc
            except LLMError:
                raise
            except Exception as exc:
                raise LLMError(f"Grok request failed: {exc}") from exc

            if attempt >= len(BACKOFF_SECONDS):
                nxt = remaining[0] if remaining else "any other available Grok model"
                log.warning("Grok %s still failing (%s) after %d retries; switching to %s", model, code, attempt, nxt)
                return None
            wait = BACKOFF_SECONDS[attempt] + random.uniform(0, 0.5)
            if code == 429:
                hinted = self._retry_after(self._last_transient)
                if hinted is not None:
                    wait = min(hinted, MAX_RETRY_DELAY)
            attempt += 1
            log.warning("Grok %s returned %s; retry %d/%d in %.1fs", model, code, attempt, len(BACKOFF_SECONDS), wait)
            time.sleep(wait)

    def _chat(self, content, json_mode: bool) -> str:
        candidates = [self.model] + [m for m in GROK_FALLBACKS if m != self.model]
        tried: list[str] = []
        self._last_error: Optional[Exception] = None
        self._last_transient: Optional[Exception] = None
        discovered = False
        while candidates:
            model = candidates.pop(0)
            if model in tried:
                continue
            tried.append(model)
            text = self._call_model(model, content, json_mode, candidates)
            if text is not None:
                if model != self.model:
                    log.warning("Grok: using %s instead of %s", model, self.model)
                    self.model = model
                return text
            if not candidates and not discovered:
                discovered = True
                candidates = [m for m in self._available_models() if m not in tried]
        if self._last_transient is not None:
            exc = self._last_transient
            code = getattr(exc, "status_code", None)
            raise LLMTransientError(
                f"Grok is overloaded or unreachable. Tried models: {', '.join(tried)}. Last error: {exc}",
                status_code=code,
                short=str(code) if code else "connection error",
            )
        raise LLMError(f"No usable Grok model found. Set LLM_MODEL to a model listed in the xAI console. Last error: {self._last_error}")

    def _available_models(self) -> list[str]:
        try:
            names = [m.id for m in self._client.models.list()]
        except Exception:
            return []
        names = [n for n in names if n.startswith("grok") and not any(x in n for x in _SKIP)]
        return sorted(set(names), key=_rank, reverse=True)

    def extract(self, text, images, prompt, schema, doc_name=None) -> dict:
        parts: list[dict] = [{"type": "text", "text": prompt}]
        for img in images or []:
            url = "data:image/png;base64," + base64.b64encode(img).decode()
            parts.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})
        if text:
            parts.append({"type": "text", "text": "INVOICE TEXT:\n" + text})
        raw = self._chat(parts, json_mode=True).strip()
        if raw.startswith("```"):  # tolerate fenced JSON if response_format had to be dropped
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Response was not valid JSON: {exc}") from exc

    def generate_text(self, prompt: str) -> str:
        return self._chat(prompt, json_mode=False).strip()
