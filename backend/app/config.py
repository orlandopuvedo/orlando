"""Application configuration loaded from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Storage
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'jobhunter.db'}"
    data_dir: Path = BACKEND_DIR / "data"

    # Server
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Optional HTTP Basic auth protecting the whole app (recommended if exposed beyond localhost)
    app_username: str | None = None
    app_password: str | None = None
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"

    # AI providers (keys only via env, never stored in DB)
    ai_provider: str = "auto"  # auto | anthropic | openai | google | ollama | none
    ai_model: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    google_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    # Automation
    scheduler_enabled: bool = True
    run_migrations_on_startup: bool = True
    http_user_agent: str = "AIJobHunter/1.0 (personal job search assistant)"
    http_timeout_seconds: float = 20.0

    # Browser agent
    browser_headless: bool = False
    browser_user_data_dir: Path = BACKEND_DIR / "data" / "browser-profile"
    browser_executable_path: str | None = None

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.uploads_dir.mkdir(parents=True, exist_ok=True)
    s.exports_dir.mkdir(parents=True, exist_ok=True)
    return s
