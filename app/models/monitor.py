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
    last_error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    platform = relationship("RelayPlatform", back_populates="account_monitors")

    @property
    def has_password(self) -> bool:
        return bool(self.password_encrypted)


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
