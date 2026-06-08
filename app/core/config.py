import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Sub2APIDatabaseSettings(BaseModel):
    dsn: str | None = None
    host: str = "sub2api-postgres"
    port: int = Field(default=5432, ge=1, le=65535)
    user: str = ""
    password: str = ""
    dbname: str = "sub2api"
    sslmode: str = "disable"
    connect_timeout_seconds: int = Field(default=5, ge=1, le=60)

    @property
    def is_configured(self) -> bool:
        return bool(self.dsn or (self.host and self.user and self.password and self.dbname))

    @property
    def has_password(self) -> bool:
        return bool(self.password or self._password_from_dsn())

    def postgresql_dsn(self) -> str:
        if self.dsn:
            return self.dsn
        user = quote(self.user, safe="")
        password = quote(self.password, safe="")
        dbname = quote(self.dbname, safe="")
        return (
            f"postgresql://{user}:{password}@{self.host}:{self.port}/{dbname}"
            f"?sslmode={quote(self.sslmode, safe='')}"
        )

    def masked_dsn(self) -> str | None:
        if not self.is_configured:
            return None
        dsn = self.postgresql_dsn()
        parts = urlsplit(dsn)
        if not parts.username:
            return dsn
        username = quote(parts.username, safe="")
        hostname = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        auth = f"{username}:<masked>@{hostname}{port}"
        return urlunsplit((parts.scheme, auth, parts.path, parts.query, parts.fragment))

    def _password_from_dsn(self) -> str | None:
        if not self.dsn:
            return None
        return urlsplit(self.dsn).password


class Sub2APISettings(BaseModel):
    database: Sub2APIDatabaseSettings = Field(default_factory=Sub2APIDatabaseSettings)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SUB2_MONITOR_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    config_file: str | None = None
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
    sub2api: Sub2APISettings = Field(default_factory=Sub2APISettings)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
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


def default_config_file() -> Path:
    docker_config = Path("/app/config/config.yaml")
    if docker_config.exists():
        return docker_config
    return Path(__file__).resolve().parents[2] / "config.yaml"


def load_config_file(path: str | None = None) -> dict[str, Any]:
    config_path = Path(path or os.getenv("SUB2_MONITOR_CONFIG_FILE") or default_config_file())
    if not config_path.exists() or not config_path.is_file():
        return {}
    raw_data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw_data, dict):
        raise ValueError(f"Config file must contain a YAML object: {config_path}")

    app_data = raw_data.get("app") or {}
    sub2api_data = raw_data.get("sub2api") or {}
    if not isinstance(app_data, dict):
        raise ValueError("Config section `app` must be a YAML object")
    if not isinstance(sub2api_data, dict):
        raise ValueError("Config section `sub2api` must be a YAML object")

    known_app_fields = set(Settings.model_fields) - {"sub2api"}
    top_level_app_data = {
        key: value
        for key, value in raw_data.items()
        if key in known_app_fields and key not in {"app", "sub2api"}
    }
    merged: dict[str, Any] = {**top_level_app_data, **app_data}
    if sub2api_data:
        merged["sub2api"] = sub2api_data
    return merged


@lru_cache
def get_settings() -> Settings:
    env_settings = Settings()
    config_data = load_config_file(env_settings.config_file)
    if not config_data:
        return env_settings
    config_data.setdefault("config_file", env_settings.config_file)
    return Settings(**config_data)
