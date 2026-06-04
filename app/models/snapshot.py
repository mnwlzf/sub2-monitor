from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.security import utcnow


class PlatformSnapshot(Base):
    __tablename__ = "platform_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("relay_platforms.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    balance: Mapped[float | None] = mapped_column(Float)
    quota_used: Mapped[float | None] = mapped_column(Float)
    quota_limit: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    platform = relationship("RelayPlatform", back_populates="snapshots")

