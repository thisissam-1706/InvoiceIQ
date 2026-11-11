from typing import Optional, Protocol

from pydantic import BaseModel


class LLMError(Exception):
    """Provider call failed (auth, network, quota, malformed response)."""


class LLMTransientError(LLMError):
    """Every candidate model kept failing with a transient error (503/500/502/504/429)."""

    def __init__(self, message: str, status_code: Optional[int] = None, short: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.short = short or (str(status_code) if status_code else "transient error")


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
