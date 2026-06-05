from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.security import utcnow


class PlatformStatus(StrEnum):
    unknown = "unknown"
    healthy = "healthy"
    degraded = "degraded"
    down = "down"


class RelayPlatform(Base):
    __tablename__ = "relay_platforms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), default="sub2api", nullable=False)
    site_strategy: Mapped[str] = mapped_column(String(64), default="generic", nullable=False)
    auth_header_name: Mapped[str] = mapped_column(String(64), default="Authorization", nullable=False)
    auth_header_prefix: Mapped[str] = mapped_column(String(32), default="Bearer", nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    balance_cron: Mapped[str] = mapped_column(String(64), default="*/10 * * * *", nullable=False)
    rate_cron: Mapped[str] = mapped_column(String(64), default="0 * * * *", nullable=False)
    recharge_amount: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    received_amount: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    balance_last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    balance_next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rate_last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rate_next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[PlatformStatus] = mapped_column(
        Enum(PlatformStatus),
        default=PlatformStatus.unknown,
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    key_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    balance: Mapped[float | None] = mapped_column(Float)
    quota_used: Mapped[float | None] = mapped_column(Float)
    quota_limit: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    snapshots = relationship("PlatformSnapshot", back_populates="platform", cascade="all, delete-orphan")
    account_monitors = relationship(
        "PlatformAccountMonitor",
        back_populates="platform",
        cascade="all, delete-orphan",
    )
    group_monitors = relationship(
        "PlatformGroupMonitor",
        back_populates="platform",
        cascade="all, delete-orphan",
    )
    discovered_group_rates = relationship(
        "PlatformDiscoveredGroupRate",
        back_populates="platform",
        cascade="all, delete-orphan",
    )

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key_encrypted)

    @property
    def effective_rate_factor(self) -> float | None:
        if self.recharge_amount <= 0 or self.received_amount <= 0:
            return None
        return self.recharge_amount / self.received_amount
