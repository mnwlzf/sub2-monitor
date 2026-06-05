from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.security import utcnow


class PlatformSnapshot(Base):
    __tablename__ = "platform_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("relay_platforms.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    balance: Mapped[float | None] = mapped_column(Float)
    quota_used: Mapped[float | None] = mapped_column(Float)
    quota_limit: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    platform = relationship("RelayPlatform", back_populates="snapshots")


class AccountBalanceSnapshot(Base):
    __tablename__ = "account_balance_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("relay_platforms.id", ondelete="CASCADE"), index=True)
    account_monitor_id: Mapped[int] = mapped_column(
        ForeignKey("platform_account_monitors.id", ondelete="CASCADE"),
        index=True,
    )
    balance: Mapped[float | None] = mapped_column(Float)
    quota_used: Mapped[float | None] = mapped_column(Float)
    quota_limit: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    account_monitor = relationship("PlatformAccountMonitor")
    platform = relationship("RelayPlatform")


class GroupRateSnapshot(Base):
    __tablename__ = "group_rate_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("relay_platforms.id", ondelete="CASCADE"), index=True)
    group_monitor_id: Mapped[int] = mapped_column(
        ForeignKey("platform_group_monitors.id", ondelete="CASCADE"),
        index=True,
    )
    rate_multiplier: Mapped[float | None] = mapped_column(Float)
    rpm_limit: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    group_monitor = relationship("PlatformGroupMonitor")
    platform = relationship("RelayPlatform")


class DiscoveredGroupRateSnapshot(Base):
    __tablename__ = "discovered_group_rate_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("relay_platforms.id", ondelete="CASCADE"), index=True)
    external_group_id: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    rate_multiplier: Mapped[float | None] = mapped_column(Float)
    rpm_limit: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    platform = relationship("RelayPlatform")
