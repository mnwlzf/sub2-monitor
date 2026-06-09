from datetime import datetime

import json
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text
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


class Sub2APIPrioritySyncRun(Base):
    __tablename__ = "sub2api_priority_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True, nullable=False)
    target_database: Mapped[str] = mapped_column(String(255), nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched_accounts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_accounts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    items_json: Mapped[str | None] = mapped_column(Text)
    executed_by_user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    executed_by_username: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def items(self) -> list[dict[str, Any]]:
        if not self.items_json:
            return []
        try:
            raw_items = json.loads(self.items_json)
        except (TypeError, ValueError):
            return []
        if not isinstance(raw_items, list):
            return []
        return [item for item in raw_items if isinstance(item, dict)]

    @items.setter
    def items(self, value: list[dict[str, Any]]) -> None:
        self.items_json = json.dumps(value, ensure_ascii=False, default=str) if value else None


class Sub2APIMonitorFailureState(Base):
    __tablename__ = "sub2api_monitor_failure_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    platform_name: Mapped[str | None] = mapped_column(String(80))
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Sub2APIMonitorSuspendedAccount(Base):
    __tablename__ = "sub2api_monitor_suspended_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    platform_name: Mapped[str | None] = mapped_column(String(80))
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(255))
    restored: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    pause_error: Mapped[str | None] = mapped_column(Text)
    restore_error: Mapped[str | None] = mapped_column(Text)
    paused_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
