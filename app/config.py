"""Validated runtime settings; credentials are never logged."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class ScoreWeights(BaseModel):
    semantic: float = Field(default=0.35, ge=0, le=1)
    skills: float = Field(default=0.25, ge=0, le=1)
    experience: float = Field(default=0.20, ge=0, le=1)
    education: float = Field(default=0.10, ge=0, le=1)
    location: float = Field(default=0.10, ge=0, le=1)

    @model_validator(mode="after")
    def validate_sum(self) -> "ScoreWeights":
        if abs(sum(self.model_dump().values()) - 1) > 1e-6:
            raise ValueError("Score weights must sum to 1")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: SecretStr = SecretStr("sqlite:///data/job_hunter.db")
    profile_path: Path = Path("profiles/default.json")
    profiles_dir: Path = Path("profiles/private")
    profiles_json: SecretStr | None = None
    migration_database_url: SecretStr | None = None
    embedding_backend: Literal["sentence-transformer", "tfidf"] = "sentence-transformer"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_revision: str = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
    model_cache_dir: Path = Path("model-cache")
    embedding_cache_dir: Path = Path("data/embeddings")
    embedding_batch_size: int = Field(default=16, ge=1, le=128)
    embedding_cpu_threads: int = Field(default=2, ge=1, le=16)
    embedding_local_files_only: bool = False
    matching_max_jobs: int = Field(default=1000, ge=1, le=5000)
    job_max_age_days: int = Field(default=45, ge=1, le=365)
    score_weights: ScoreWeights = Field(default_factory=ScoreWeights)
    minimum_match_score: float = Field(default=65, ge=0, le=100)
    max_notifications_per_day: int = Field(default=10, ge=1, le=100)
    notification_timezone: str = "Africa/Algiers"
    notification_max_attempts: int = Field(default=3, ge=1, le=10)
    enable_jobicy: bool = True
    jobicy_max_pages: int = Field(default=2, ge=1, le=5)
    source_cache_dir: Path = Path("data/source-cache")
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: SecretStr | None = None
    qwen_api_key: SecretStr | None = None
    qwen_base_url: str | None = None
    qwen_model: str = "qwen-plus"
    llm_provider: Literal["groq", "qwen"] = "groq"
    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-20b"
    llm_enabled: bool = False
    pipeline_enabled: bool = False
    notifications_enabled: bool = False
    arbeitnow_max_pages: int = Field(default=1, ge=1, le=10)
    http_timeout_seconds: float = Field(default=30, gt=0, le=120)
    http_max_attempts: int = Field(default=3, ge=1, le=5)
    http_retry_base_seconds: float = Field(default=1, ge=0, le=30)
    request_interval_seconds: float = Field(default=1, ge=0, le=60)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("DATABASE_URL must be a valid SQLAlchemy URL") from None
        if url.drivername not in {"sqlite", "postgresql+psycopg"}:
            raise ValueError("Use sqlite or postgresql+psycopg")
        if url.drivername == "sqlite" and not url.database:
            raise ValueError("SQLite requires a file path or :memory:")
        return value

    @field_validator("notification_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("Unknown notification timezone") from None
        return value

    @field_validator("qwen_base_url", "groq_base_url")
    @classmethod
    def valid_qwen_url(cls, value: str | None) -> str | None:
        from urllib.parse import urlsplit

        if not value:
            return None
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query:
            raise ValueError("LLM base URL must be HTTPS without credentials/query")
        return value.rstrip("/")

    @field_validator(
        "telegram_bot_token",
        "telegram_chat_id",
        "qwen_api_key",
        "groq_api_key",
        "profiles_json",
        "migration_database_url",
        mode="before",
    )
    @classmethod
    def blank_secret_is_unset(cls, value):
        return None if value == "" else value
