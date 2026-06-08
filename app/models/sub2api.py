from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.security import utcnow


class Sub2APISQLLog(Base):
    __tablename__ = "sub2api_sql_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    target_database: Mapped[str] = mapped_column(String(255), nullable=False)
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    sql_params_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    affected_rows: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    executed_by_user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    executed_by_username: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
