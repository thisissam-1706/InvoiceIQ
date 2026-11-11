from typing import Optional, Protocol

from pydantic import BaseModel


class LLMError(Exception):
    """Provider call failed (auth, network, quota, malformed response)."""


class LLMUnavailable(LLMError):
    """Provider cannot do this kind of task at all (e.g. offline text generation)."""


class LLMClient(Protocol):
    provider: str
    model: str

    def extract(
        self,
        text: Optional[str],
        images: Optional[list[bytes]],
        prompt: str,
        schema: type[BaseModel],
        doc_name: Optional[str] = None,
    ) -> dict: ...

    def generate_text(self, prompt: str) -> str: ...
