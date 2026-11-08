"""Application configuration loaded strictly from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _parse_cors_origins(raw: str) -> list[str]:
    if not raw.strip():
        return ["http://localhost:5173", "http://127.0.0.1:5173"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@dataclass(frozen=True)
class Settings:
    """Immutable runtime configuration. Secrets are read from env and never logged."""

    groq_api_key: str = field(default_factory=lambda: os.environ.get("GROQ_API_KEY", ""), repr=False)
    tavily_api_key: str = field(default_factory=lambda: os.environ.get("TAVILY_API_KEY", ""), repr=False)
    ledger_secret: str = field(
        default_factory=lambda: os.environ.get("NEXUS_LEDGER_SECRET", "dev-insecure-ledger-hmac-key-change-me"),
        repr=False,
    )
    groq_model: str = field(default_factory=lambda: os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"))
    groq_base_url: str = field(
        default_factory=lambda: os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    )
    tavily_base_url: str = field(
        default_factory=lambda: os.environ.get("TAVILY_BASE_URL", "https://api.tavily.com")
    )
    database_path: str = field(
        default_factory=lambda: os.environ.get("NEXUS_DB_PATH", "/tmp/nexus_agentis.db")
    )
    checkpoint_db_path: str = field(
        default_factory=lambda: os.environ.get("NEXUS_CHECKPOINT_DB_PATH", "/tmp/nexus_checkpoints.db")
    )
    cors_origins: list[str] = field(
        default_factory=lambda: _parse_cors_origins(os.environ.get("CORS_ORIGINS", ""))
    )
    default_token_budget: int = field(
        default_factory=lambda: int(os.environ.get("DEFAULT_TOKEN_BUDGET", "32000"))
    )
    max_token_budget: int = field(
        default_factory=lambda: int(os.environ.get("MAX_TOKEN_BUDGET", "128000"))
    )
    default_max_loops: int = field(
        default_factory=lambda: int(os.environ.get("DEFAULT_MAX_LOOPS", "3"))
    )
    default_support_threshold: float = field(
        default_factory=lambda: float(os.environ.get("DEFAULT_SUPPORT_THRESHOLD", "0.75"))
    )
    min_credible_sources_per_section: int = field(
        default_factory=lambda: int(os.environ.get("MIN_CREDIBLE_SOURCES", "2"))
    )
    credibility_threshold: float = field(
        default_factory=lambda: float(os.environ.get("CREDIBILITY_THRESHOLD", "0.60"))
    )
    run_timeout_seconds: float = field(
        default_factory=lambda: float(os.environ.get("RUN_TIMEOUT_SECONDS", "180.0"))
    )
    max_concurrent_runs: int = field(
        default_factory=lambda: int(os.environ.get("MAX_CONCURRENT_RUNS", "4"))
    )
    max_request_bytes: int = field(
        default_factory=lambda: int(os.environ.get("MAX_REQUEST_BYTES", "32768"))
    )
    rate_limit_rpm: int = field(
        default_factory=lambda: int(os.environ.get("RATE_LIMIT_RPM", "30"))
    )
    stub_external_apis: bool = field(
        default_factory=lambda: os.environ.get("NEXUS_STUB_APIS", "false").lower() in ("1", "true", "yes")
    )


def get_settings() -> Settings:
    return Settings()
