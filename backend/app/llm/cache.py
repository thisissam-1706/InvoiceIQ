import hashlib
import json
from pathlib import Path
from typing import Optional

from ..settings import LLM_CACHE_DIR


def cache_key(file_sha256: str, provider: str, model: str, prompt_version: str) -> str:
    return hashlib.sha256(f"{file_sha256}|{provider}|{model}|{prompt_version}".encode()).hexdigest()


class ResponseCache:
    def __init__(self, directory: Path = LLM_CACHE_DIR):
        self.directory = directory

    def get(self, key: str) -> Optional[dict]:
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None

    def put(self, key: str, payload: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.directory / f"{key}.tmp"
        tmp.write_text(json.dumps(payload, indent=1))
        tmp.replace(self.directory / f"{key}.json")

    def count(self) -> int:
        return len(list(self.directory.glob("*.json"))) if self.directory.exists() else 0
