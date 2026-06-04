from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SUB2_MONITOR_",
        extra="ignore",
    )

    app_name: str = "Sub2 Monitor"
    env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    database_url: str = "sqlite:///./data/sub2-monitor.db"
    secret_key: str = Field(default="dev-only-change-me")
    bootstrap_username: str = "admin"
    bootstrap_password: str = "change-this-password"
    session_cookie_name: str = "sub2_monitor_session"
    session_ttl_seconds: int = 60 * 60 * 12
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def frontend_dist(self) -> Path:
        return self.project_root / "frontend" / "dist"

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"prod", "production"}


@lru_cache
def get_settings() -> Settings:
    return Settings()

