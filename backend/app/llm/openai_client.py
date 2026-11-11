import base64
import json

from .base import LLMError


class OpenAIClient:
    provider = "openai"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise LLMError("OPENAI_API_KEY is empty. Add it to .env or set LLM_PROVIDER=offline.")
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.model = model

    def _chat(self, content, json_mode: bool) -> str:
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[{"role": "user", "content": content}],
                **kwargs,
            )
        except Exception as exc:
            raise LLMError(f"OpenAI request failed: {exc}") from exc
        text = response.choices[0].message.content
        if not text:
            raise LLMError("OpenAI returned an empty response")
        return text

    def extract(self, text, images, prompt, schema, doc_name=None) -> dict:
        parts: list[dict] = [{"type": "text", "text": prompt}]
        for img in images or []:
            url = "data:image/png;base64," + base64.b64encode(img).decode()
            parts.append({"type": "image_url", "image_url": {"url": url}})
        if text:
            parts.append({"type": "text", "text": "INVOICE TEXT:\n" + text})
        raw = self._chat(parts, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Response was not valid JSON: {exc}") from exc

    def generate_text(self, prompt: str) -> str:
        return self._chat(prompt, json_mode=False).strip()
