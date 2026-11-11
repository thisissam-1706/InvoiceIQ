import json
import logging
import random
import re
import time
from typing import Optional

from .base import LLMError, LLMTransientError

log = logging.getLogger(__name__)

TRANSIENT_CODES = {429, 500, 502, 503, 504}
BACKOFF_SECONDS = [2.0, 6.0]  # waits before retry 1 and retry 2 on the same model
MAX_RETRY_DELAY = 20.0

# Tried in order when the configured model name is rejected by the API.
# Google retires model names regularly, so if all of these 404 too, the client
# asks the API which Flash models this key can use and picks the newest one.
FLASH_FALLBACKS = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-latest", "gemini-flash-lite-latest"]
_SKIP = ("image", "tts", "live", "audio", "embedding", "native", "computer-use", "exp")


def _rank(name: str) -> tuple:
    """Sort key: stable before preview, full Flash before Lite, then newest version."""
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    version = float(m.group(1)) if m else 0.0
    return ("preview" not in name, "lite" not in name, version)


class GeminiClient:
    provider = "gemini"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is empty. Add it to .env or set LLM_PROVIDER=offline.")
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self.model = model

    @staticmethod
    def _retry_delay(exc) -> Optional[float]:
        """Seconds from the API's RetryInfo.retryDelay (e.g. "13s" or "13.5s"), if present."""
        def walk(node):
            if isinstance(node, dict):
                if "retryDelay" in node:
                    yield node["retryDelay"]
                for v in node.values():
                    yield from walk(v)
            elif isinstance(node, list):
                for v in node:
                    yield from walk(v)

        for value in walk(getattr(exc, "details", None)):
            m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s?\s*", str(value))
            if m:
                return float(m.group(1))
        m = re.search(r"retry(?:Delay)?\D{0,12}(\d+(?:\.\d+)?)s", str(exc))
        return float(m.group(1)) if m else None

    def _call_model(self, model: str, contents: list, config, remaining: list[str]):
        """Call one model, retrying transient errors. Returns the response, or None to move on to the next model."""
        from google.genai import errors

        attempt = 0
        while True:
            try:
                return self._client.models.generate_content(model=model, contents=contents, config=config)
            except errors.APIError as exc:
                code = getattr(exc, "code", None)
                if code == 404:
                    self._last_error = exc
                    return None
                if code not in TRANSIENT_CODES:
                    detail = getattr(exc, "message", None) or str(exc)
                    raise LLMError(f"Gemini request failed ({code} {getattr(exc, 'status', '')}): {detail}") from exc
                self._last_error = self._last_transient = exc
                if attempt >= len(BACKOFF_SECONDS):
                    nxt = remaining[0] if remaining else "any other available Flash model"
                    log.warning("Gemini %s still failing with %s after %d retries; switching to %s", model, code, attempt, nxt)
                    return None
                wait = BACKOFF_SECONDS[attempt] + random.uniform(0, 0.5)
                if code == 429:
                    hinted = self._retry_delay(exc)
                    if hinted is not None:
                        wait = min(hinted, MAX_RETRY_DELAY)
                attempt += 1
                log.warning("Gemini %s returned %s; retry %d/%d in %.1fs", model, code, attempt, len(BACKOFF_SECONDS), wait)
                time.sleep(wait)
            except Exception as exc:
                raise LLMError(f"Gemini request failed: {exc}") from exc

    def _generate(self, contents: list, json_mode: bool) -> str:
        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json" if json_mode else "text/plain",
        )
        candidates = [self.model] + [m for m in FLASH_FALLBACKS if m != self.model]
        tried: list[str] = []
        self._last_error: Optional[Exception] = None
        self._last_transient: Optional[Exception] = None
        discovered = False
        while candidates:
            model = candidates.pop(0)
            if model in tried:
                continue
            tried.append(model)
            response = self._call_model(model, contents, config, candidates)
            if response is not None:
                if model != self.model:
                    log.warning("Gemini: using %s instead of %s", model, self.model)
                    self.model = model
                if not response.text:
                    raise LLMError("Gemini returned an empty response")
                return response.text
            if not candidates and not discovered:
                discovered = True
                candidates = [m for m in self._available_flash_models() if m not in tried]
        if self._last_transient is not None:
            exc = self._last_transient
            code = getattr(exc, "code", None)
            status = getattr(exc, "status", "") or ""
            raise LLMTransientError(
                f"Gemini is overloaded. Tried models: {', '.join(tried)}. Last error: {code} {status}: "
                f"{getattr(exc, 'message', None) or exc}",
                status_code=code,
                short=f"{code} {status}".strip(),
            )
        raise LLMError(
            f"No usable Gemini Flash model found. Set LLM_MODEL to a model listed in Google AI Studio. Last error: {self._last_error}"
        )

    def _available_flash_models(self) -> list[str]:
        """Ask the API which text Flash models this key can call, best first."""
        try:
            models = list(self._client.models.list())
        except Exception:
            return []
        names = []
        for m in models:
            name = (getattr(m, "name", "") or "").removeprefix("models/")
            actions = getattr(m, "supported_actions", None) or []
            if "flash" in name and "generateContent" in actions and not any(x in name for x in _SKIP):
                names.append(name)
        return sorted(set(names), key=_rank, reverse=True)

    def extract(self, text, images, prompt, schema, doc_name=None) -> dict:
        from google.genai import types

        contents: list = [prompt]
        if images:
            contents += [types.Part.from_bytes(data=img, mime_type="image/png") for img in images]
        if text:
            contents.append("INVOICE TEXT:\n" + text)
        raw = self._generate(contents, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Response was not valid JSON: {exc}") from exc

    def generate_text(self, prompt: str) -> str:
        return self._generate([prompt], json_mode=False).strip()
