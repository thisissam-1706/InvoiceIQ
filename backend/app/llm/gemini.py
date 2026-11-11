import json
import re
from typing import Optional

from .base import LLMError

# Tried in order when the configured model name is rejected by the API.
# Google retires model names regularly, so if all of these 404 too, the client
# asks the API which Flash models this key can use and picks the newest one.
FLASH_FALLBACKS = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-latest"]
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

    def _generate(self, contents: list, json_mode: bool) -> str:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json" if json_mode else "text/plain",
        )
        candidates = [self.model] + [m for m in FLASH_FALLBACKS if m != self.model]
        last_error: Optional[Exception] = None
        discovered = False
        while candidates:
            model = candidates.pop(0)
            try:
                response = self._client.models.generate_content(model=model, contents=contents, config=config)
            except errors.ClientError as exc:
                if getattr(exc, "code", None) == 404:
                    last_error = exc
                    if not candidates and not discovered:
                        discovered = True
                        candidates = [m for m in self._available_flash_models() if m not in (model, self.model)]
                    continue
                detail = getattr(exc, "message", None) or str(exc)
                raise LLMError(f"Gemini request failed ({exc.code} {getattr(exc, 'status', '')}): {detail}") from exc
            except Exception as exc:
                raise LLMError(f"Gemini request failed: {exc}") from exc
            if model != self.model:
                self.model = model
            if not response.text:
                raise LLMError("Gemini returned an empty response")
            return response.text
        raise LLMError(
            f"No usable Gemini Flash model found. Set LLM_MODEL to a model listed in Google AI Studio. Last error: {last_error}"
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
