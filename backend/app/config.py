"""Centralized settings, read from environment variables and backend/.env.

Set APP_ENV_FILE to point at a different env file (the test suite sets it to an empty value so
local secrets never leak into test runs)."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = os.getenv("APP_ENV_FILE", str(BACKEND_DIR / ".env")) or None

ReasoningEffort = Literal["low", "medium", "high"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    # --- Groq (LLM reasoning) ---
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_timeout_seconds: float = 45.0
    # Reasoning effort for the two small background/auxiliary calls (memory extraction, preference
    # learning). Only sent to models that accept it; the main analysis uses the model default.
    groq_aux_reasoning_effort: ReasoningEffort | None = "low"

    # --- Hindsight (agent memory) ---
    hindsight_api_key: str = ""
    hindsight_base_url: str = "https://api.hindsight.vectorize.io"
    hindsight_bank_id: str = "incident-response-agent"  # prefix; each user gets "<prefix>-u-<user_id>"
    hindsight_timeout_seconds: float = 60.0  # SDK timeout (synchronous retain runs fact extraction)
    # Recall is on the critical path: past this budget the analysis proceeds without history.
    hindsight_recall_timeout_seconds: float = 15.0
    hindsight_recall_max_tokens: int = 2048
    # Minimum reranker relevance for a memory from a *different* service to be shown.
    hindsight_min_relevance: float = 0.3
    # Floor for same-service memories, so an unrelated incident on the same service is not shown.
    hindsight_min_relevance_same_service: float = 0.1
    recall_max_incidents: int = 3
    recall_max_facts_per_incident: int = 4
    recall_max_loose_facts: int = 3

    # --- Prompt budget ---
    prompt_max_log_chars: int = 3000

    # --- Auth ---
    session_ttl_hours: int = 24 * 7
    # Legacy single-login migration only. Empty password = never create the legacy account.
    demo_username: str = "admin"
    demo_password: str = ""

    # --- App ---
    database_path: Path = BACKEND_DIR / "incidents.db"
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://frontend-rouge-two-76.vercel.app",
    ]
    # Include per-stage latency/token metrics in API responses (no incident content is exposed).
    expose_metrics: bool = True
    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, v: object) -> object:
        """Accept a comma-separated CORS_ORIGINS env var as well as a list."""
        if isinstance(v, str):
            return [o.strip().rstrip("/") for o in v.split(",") if o.strip()]
        return v

    def secret_values(self) -> list[str]:
        """Configured secrets, for log redaction."""
        return [s for s in (self.groq_api_key, self.hindsight_api_key, self.demo_password) if len(s) >= 6]


@lru_cache
def get_settings() -> Settings:
    return Settings()
