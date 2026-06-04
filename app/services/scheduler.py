import asyncio
import logging
from contextlib import suppress
from datetime import datetime

from croniter import croniter
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import utcnow
from app.models.platform import RelayPlatform
from app.services.monitoring import run_platform_balance_monitor, run_platform_rate_monitor

logger = logging.getLogger(__name__)


class MonitorScheduler:
    def __init__(self, interval_seconds: int = 30) -> None:
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                logger.exception("monitor scheduler tick failed")
            await asyncio.sleep(self.interval_seconds)

    async def tick(self) -> None:
        now = utcnow()
        with SessionLocal() as db:
            platforms = list(
                db.scalars(select(RelayPlatform).where(RelayPlatform.enabled.is_(True))).all()
            )
            due_balance: list[int] = []
            due_rate: list[int] = []
            for platform in platforms:
                if self._ensure_next_run(platform.balance_next_run_at, platform.balance_cron, now):
                    platform.balance_next_run_at = croniter(platform.balance_cron, now).get_next(datetime)
                    db.add(platform)
                if self._ensure_next_run(platform.rate_next_run_at, platform.rate_cron, now):
                    platform.rate_next_run_at = croniter(platform.rate_cron, now).get_next(datetime)
                    db.add(platform)
                if platform.balance_next_run_at and platform.balance_next_run_at <= now:
                    due_balance.append(platform.id)
                if platform.rate_next_run_at and platform.rate_next_run_at <= now:
                    due_rate.append(platform.id)
            db.commit()

        for platform_id in due_balance:
            try:
                with SessionLocal() as db:
                    await run_platform_balance_monitor(db, platform_id)
            except Exception:  # noqa: BLE001
                logger.exception("scheduled balance monitor failed for platform_id=%s", platform_id)
        for platform_id in due_rate:
            try:
                with SessionLocal() as db:
                    await run_platform_rate_monitor(db, platform_id)
            except Exception:  # noqa: BLE001
                logger.exception("scheduled rate monitor failed for platform_id=%s", platform_id)

    @staticmethod
    def _ensure_next_run(next_run_at: datetime | None, cron_expr: str, now: datetime) -> bool:
        return next_run_at is None and bool(cron_expr)
