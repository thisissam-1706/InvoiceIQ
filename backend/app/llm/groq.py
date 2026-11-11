"""Groq (GroqCloud) via its OpenAI-compatible API (https://api.groq.com/openai/v1)."""

import base64
import io
import json
import logging
import random
import re
import time
from typing import Optional

from .base import LLMError, LLMTransientError

log = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
TRANSIENT_CODES = {429, 500, 502, 503, 504}
BACKOFF_SECONDS = [2.0, 6.0]  # waits before retry 1 and retry 2 on the same model
MAX_RETRY_DELAY = 20.0
# Models that read images as well as text, tried in order after the configured model.
VISION_FALLBACKS = ["qwen/qwen3.6-27b", "qwen/qwen3.8-27b", "meta-llama/llama-4-scout-17b-16e-instruct"]
# Extra text-only models, used only for requests without images.
TEXT_FALLBACKS = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b"]
_VISION_HINTS = ("qwen3.", "llama-4", "vision", "scout", "maverick")
_SKIP = ("whisper", "tts", "playai", "guard", "orpheus", "compound", "embed")
_THINK = re.compile(r"<think>.*?</think>", re.S)


def _to_jpeg_data_url(png: bytes) -> str:
    """Groq caps base64 images at 4 MB; a 200 DPI PNG page is ~3.5 MB, so send JPEG instead."""
    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class GroqClient:
    provider = "groq"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise LLMError("GROQ_API_KEY is empty. Add it to .env or set LLM_PROVIDER=offline.")
        from openai import OpenAI

        # No request timeout (timeout=None) and no SDK-level retries: retries are handled below.
        self._client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL, timeout=None, max_retries=0)
        self.model = model
        self._dropped: set[str] = set()  # request options a model rejected (e.g. reasoning_format)

    @staticmethod
    def _retry_after(exc) -> Optional[float]:
        response = getattr(exc, "response", None)
        value = response.headers.get("retry-after") if response is not None else None
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None

    def _options(self, json_mode: bool) -> dict:
        opts: dict = {}
        if "temperature" not in self._dropped:
            opts["temperature"] = 0
        if json_mode and "response_format" not in self._dropped:
            opts["response_format"] = {"type": "json_object"}
        if "reasoning_format" not in self._dropped:
            # Qwen 3 models think before answering; keep the thinking out of the answer text.
            opts["extra_body"] = {"reasoning_format": "hidden"}
        return opts

    def _call_model(self, model: str, content, json_mode: bool, remaining: list[str]) -> Optional[str]:
        """Call one model, retrying transient errors. Returns text, or None to move on to the next model."""
        import openai

        attempt = 0
        while True:
            code = None
            try:
                response = self._client.chat.completions.create(
                    model=model, messages=[{"role": "user", "content": content}], **self._options(json_mode)
                )
                text = _THINK.sub("", response.choices[0].message.content or "").strip()
                if not text:
                    raise LLMError("Groq returned an empty response")
                return text
            except openai.APIStatusError as exc:
                code = exc.status_code
                message = str(getattr(exc, "message", "") or exc).lower()
                if code == 400:
                    rejected = next(
                        (o for o in ("reasoning_format", "response_format", "temperature") if o in message and o not in self._dropped),
                        None,
                    )
                    if rejected:
                        log.warning("Groq %s rejected %s; retrying without it", model, rejected)
                        self._dropped.add(rejected)
                        continue
                    if "image" in message or "vision" in message:  # model cannot read images
                        self._last_error = exc
                        return None
                if code == 404 or (code == 400 and "model" in message and ("not" in message or "decommission" in message)):
                    self._last_error = exc
                    return None
                if code not in TRANSIENT_CODES:
                    raise LLMError(f"Groq request failed ({code}): {getattr(exc, 'message', exc)}") from exc
                self._last_error = self._last_transient = exc
            except openai.APIConnectionError as exc:
                self._last_error = self._last_transient = exc
            except LLMError:
                raise
            except Exception as exc:
                raise LLMError(f"Groq request failed: {exc}") from exc

            if attempt >= len(BACKOFF_SECONDS):
                nxt = remaining[0] if remaining else "any other available Groq model"
                log.warning("Groq %s still failing (%s) after %d retries; switching to %s", model, code, attempt, nxt)
                return None
            wait = BACKOFF_SECONDS[attempt] + random.uniform(0, 0.5)
            if code == 429:
                hinted = self._retry_after(self._last_transient)
                if hinted is not None:
                    wait = min(hinted, MAX_RETRY_DELAY)
            attempt += 1
            log.warning("Groq %s returned %s; retry %d/%d in %.1fs", model, code, attempt, len(BACKOFF_SECONDS), wait)
            time.sleep(wait)

    def _chat(self, content, json_mode: bool, has_images: bool) -> str:
        fallbacks = VISION_FALLBACKS + ([] if has_images else TEXT_FALLBACKS)
        candidates = [self.model] + [m for m in fallbacks if m != self.model]
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
                if model != self.model and not has_images:
                    log.warning("Groq: using %s instead of %s", model, self.model)
                elif model != self.model:
                    log.warning("Groq: read images with %s instead of %s", model, self.model)
                return text
            if not candidates and not discovered:
                discovered = True
                candidates = [m for m in self._available_models(has_images) if m not in tried]
        if self._last_transient is not None:
            exc = self._last_transient
            code = getattr(exc, "status_code", None)
            raise LLMTransientError(
                f"Groq is overloaded or unreachable. Tried models: {', '.join(tried)}. Last error: {exc}",
                status_code=code,
                short=str(code) if code else "connection error",
            )
        raise LLMError(f"No usable Groq model found. Set LLM_MODEL to a model listed at console.groq.com/docs/models. Last error: {self._last_error}")

    def _available_models(self, has_images: bool) -> list[str]:
        try:
            names = [m.id for m in self._client.models.list()]
        except Exception:
            return []
        names = [n for n in names if not any(x in n.lower() for x in _SKIP)]
        if has_images:
            names = [n for n in names if any(h in n.lower() for h in _VISION_HINTS)]
        return sorted(set(names))

    def extract(self, text, images, prompt, schema, doc_name=None) -> dict:
        parts: list[dict] = [{"type": "text", "text": prompt}]
        for img in images or []:
            parts.append({"type": "image_url", "image_url": {"url": _to_jpeg_data_url(img)}})
        if text:
            parts.append({"type": "text", "text": "INVOICE TEXT:\n" + text})
        raw = self._chat(parts, json_mode=True, has_images=bool(images))
        if raw.startswith("```"):  # tolerate fenced JSON if response_format had to be dropped
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Response was not valid JSON: {exc}") from exc

    def generate_text(self, prompt: str) -> str:
        return self._chat(prompt, json_mode=False, has_images=False)
