import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.security import utcnow


class PlatformAccountMonitor(Base):
    __tablename__ = "platform_account_monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("relay_platforms.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(120), nullable=False)
    username: Mapped[str | None] = mapped_column(String(160))
    password_encrypted: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    balance: Mapped[float | None] = mapped_column(Float)
    quota_used: Mapped[float | None] = mapped_column(Float)
    quota_limit: Mapped[float | None] = mapped_column(Float)
    key_summaries_json: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    platform = relationship("RelayPlatform", back_populates="account_monitors")

    @property
    def has_password(self) -> bool:
        return bool(self.password_encrypted)

    @property
    def key_summaries(self) -> list[dict[str, str | None]]:
        if not self.key_summaries_json:
            return []
        try:
            raw_items = json.loads(self.key_summaries_json)
        except (TypeError, ValueError):
            return []
        if not isinstance(raw_items, list):
            return []

        summaries: list[dict[str, str | None]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            key_id = raw_item.get("id")
            name = raw_item.get("name")
            group_id = raw_item.get("group_id")
            group_name = raw_item.get("group_name")
            summaries.append(
                {
                    "id": str(key_id) if key_id is not None else "",
                    "name": str(name or key_id or "未命名密钥"),
                    "group_id": str(group_id) if group_id is not None else None,
                    "group_name": str(group_name) if group_name else None,
                }
            )
        return summaries

    @key_summaries.setter
    def key_summaries(
        self,
        value: list[dict[str, str | None]] | tuple[dict[str, str | None], ...],
    ) -> None:
        self.key_summaries_json = json.dumps(list(value), ensure_ascii=False) if value else None


class PlatformGroupMonitor(Base):
    __tablename__ = "platform_group_monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("relay_platforms.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    external_group_id: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rate_multiplier: Mapped[float | None] = mapped_column(Float)
    rpm_limit: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    platform = relationship("RelayPlatform", back_populates="group_monitors")

    @property
    def effective_rate_multiplier(self) -> float | None:
        if self.rate_multiplier is None or self.platform.effective_rate_factor is None:
            return None
        return self.rate_multiplier * self.platform.effective_rate_factor


class PlatformDiscoveredGroupRate(Base):
    __tablename__ = "platform_discovered_group_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("relay_platforms.id"), index=True)
    external_group_id: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    rate_multiplier: Mapped[float | None] = mapped_column(Float)
    rpm_limit: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    platform = relationship("RelayPlatform", back_populates="discovered_group_rates")

    @property
    def effective_rate_multiplier(self) -> float | None:
        if self.rate_multiplier is None or self.platform.effective_rate_factor is None:
            return None
        return self.rate_multiplier * self.platform.effective_rate_factor

    @property
    def configured_monitor_id(self) -> int | None:
        for group in self.platform.group_monitors:
            if group.external_group_id == self.external_group_id:
                return group.id
        return None

    @property
    def is_configured(self) -> bool:
        return self.configured_monitor_id is not None


class PlatformDiscoveredChannelRate(Base):
    __tablename__ = "platform_discovered_channel_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("relay_platforms.id"), index=True)
    external_channel_id: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    base_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(64))
    rate_multiplier: Mapped[float | None] = mapped_column(Float)
    model_rates_json: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    platform = relationship("RelayPlatform", back_populates="discovered_channel_rates")

    @property
    def model_rates(self) -> dict[str, float]:
        if not self.model_rates_json:
            return {}
        try:
            raw_items = json.loads(self.model_rates_json)
        except (TypeError, ValueError):
            return {}
        if not isinstance(raw_items, dict):
            return {}

        model_rates: dict[str, float] = {}
        for model_name, value in raw_items.items():
            if not isinstance(model_name, str):
                continue
            if isinstance(value, int | float):
                model_rates[model_name] = float(value)
                continue
            if isinstance(value, str):
                try:
                    model_rates[model_name] = float(value)
                except ValueError:
                    continue
        return model_rates

    @model_rates.setter
    def model_rates(self, value: dict[str, float] | None) -> None:
        self.model_rates_json = json.dumps(value, ensure_ascii=False) if value else None
