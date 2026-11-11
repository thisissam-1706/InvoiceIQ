from dataclasses import dataclass
from typing import Optional

from ..settings import load_env
from .base import LLMClient, LLMError, LLMTransientError, LLMUnavailable
from .offline import OfflineClient


@dataclass
class ResolvedClient:
    client: LLMClient
    note: Optional[str] = None


def build_client() -> ResolvedClient:
    """Build the configured provider; a missing key degrades to offline with a visible note."""
    env = load_env()
    try:
        if env.llm_provider == "groq":
            from .groq import GroqClient

            return ResolvedClient(GroqClient(env.groq_api_key, env.llm_model))
        if env.llm_provider == "gemini":
            from .gemini import GeminiClient

            return ResolvedClient(GeminiClient(env.gemini_api_key, env.llm_model))
        if env.llm_provider == "openai":
            from .openai_client import OpenAIClient

            return ResolvedClient(OpenAIClient(env.openai_api_key, env.llm_model))
    except LLMError as exc:
        return ResolvedClient(OfflineClient(), note=f"{exc} Using the offline extractor instead.")
    return ResolvedClient(OfflineClient())


__all__ = ["LLMClient", "LLMError", "LLMTransientError", "LLMUnavailable", "OfflineClient", "ResolvedClient", "build_client"]
