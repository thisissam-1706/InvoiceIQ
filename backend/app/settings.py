import os
import threading
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
DATA_DIR = BACKEND_DIR / "data"
REFERENCE_DIR = DATA_DIR / "reference"
SAMPLES_DIR = DATA_DIR / "samples"
UPLOADS_DIR = DATA_DIR / "uploads"
INBOX_DIR = DATA_DIR / "inbox"
LLM_CACHE_DIR = DATA_DIR / "llm_cache"
FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
CONFIG_PATH = ROOT_DIR / "config.yaml"

DEFAULT_MODELS = {"groq": "qwen/qwen3.6-27b", "gemini": "gemini-3.8-flash", "openai": "gpt-4o-mini", "offline": "heuristic-v1"}
# A model name that clearly belongs to another provider is ignored (e.g. LLM_MODEL=gemini-... with LLM_PROVIDER=groq).
_MODEL_PREFIXES = {"gemini": ("gemini",), "openai": ("gpt", "o1", "o3", "o4", "chatgpt")}
_NOT_GROQ = ("gemini", "grok", "gpt-", "o1", "o3", "o4", "chatgpt")

load_dotenv(ROOT_DIR / ".env")


class Tolerance(BaseModel):
    unit_price_pct: Decimal = Field(Decimal("0.02"), ge=0, le=Decimal("0.5"))
    total_abs: Decimal = Field(Decimal("25.00"), ge=0, le=100000)
    total_pct: Decimal = Field(Decimal("0.01"), ge=0, le=Decimal("0.5"))
    po_overrun_pct: Decimal = Field(Decimal("0.00"), ge=0, le=Decimal("0.5"))


class ExtractionConfig(BaseModel):
    min_confidence: float = Field(0.70, ge=0, le=1)


class Policy(BaseModel):
    auto_approve_max_amount: Decimal = Field(Decimal("50000"), ge=0)
    never_auto_approve_on: list[str] = Field(
        default_factory=lambda: ["BANK_DETAILS_MISMATCH", "LLM_FALLBACK_OFFLINE", "PO_INFERRED", "VENDOR_FUZZY_MATCH"]
    )

    @field_validator("never_auto_approve_on")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        return sorted({c.strip().upper() for c in v if c.strip()})


class DemoConfig(BaseModel):
    stage_delay_ms: int = Field(350, ge=0, le=5000)
    inbox_poll_seconds: float = Field(3.0, ge=0.5, le=60)


class LLMConfig(BaseModel):
    cache_enabled: bool = True


class AppConfig(BaseModel):
    tolerance: Tolerance = Field(default_factory=Tolerance)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    policy: Policy = Field(default_factory=Policy)
    demo: DemoConfig = Field(default_factory=DemoConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)


def _yaml_ready(value):
    if isinstance(value, dict):
        return {k: _yaml_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_yaml_ready(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    return value


class ConfigStore:
    """Thread-safe holder for config.yaml; edits are written back to disk."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._config = self._load()

    def _load(self) -> AppConfig:
        if self.path.exists():
            raw = yaml.safe_load(self.path.read_text()) or {}
            return AppConfig.model_validate(raw)
        return AppConfig()

    def get(self) -> AppConfig:
        with self._lock:
            return self._config.model_copy(deep=True)

    def update(self, new: AppConfig, persist: bool = True) -> AppConfig:
        with self._lock:
            self._config = new.model_copy(deep=True)
            if persist:
                self.path.write_text(yaml.safe_dump(_yaml_ready(new.model_dump()), sort_keys=False))
            return self._config.model_copy(deep=True)


@dataclass
class EnvSettings:
    llm_provider: str
    llm_model: str
    gemini_api_key: str
    openai_api_key: str
    groq_api_key: str
    db_path: Path


def load_env() -> EnvSettings:
    provider = os.getenv("LLM_PROVIDER", "groq").strip().lower() or "groq"
    if provider not in DEFAULT_MODELS:
        provider = "offline"
    model = os.getenv("LLM_MODEL", "").strip()
    if provider in _MODEL_PREFIXES and model and not model.lower().startswith(_MODEL_PREFIXES[provider]):
        model = ""
    if provider == "groq" and model.lower().startswith(_NOT_GROQ):
        model = ""
    if not model or provider == "offline":
        model = DEFAULT_MODELS[provider]
    return EnvSettings(
        llm_provider=provider,
        llm_model=model,
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        db_path=Path(os.getenv("INVOICEIQ_DB", str(DATA_DIR / "invoiceiq.db"))),
    )


config_store = ConfigStore(Path(os.getenv("INVOICEIQ_CONFIG", str(CONFIG_PATH))))
