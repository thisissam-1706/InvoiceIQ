import json
from typing import Optional

from .base import LLMError

# Tried in order when the configured model name is rejected by the API.
FLASH_FALLBACKS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]


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
        for model in candidates:
            try:
                response = self._client.models.generate_content(model=model, contents=contents, config=config)
            except errors.ClientError as exc:
                if getattr(exc, "code", None) == 404:
                    last_error = exc
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
        raise LLMError(f"No usable Gemini Flash model found: {last_error}")

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
