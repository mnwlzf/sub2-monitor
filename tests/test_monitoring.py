import asyncio

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models.all  # noqa: F401
from app.core.database import Base
from app.models.monitor import PlatformGroupMonitor
from app.models.platform import PlatformStatus, RelayPlatform
from app.models.snapshot import GroupRateSnapshot
from app.services.monitoring import run_platform_rate_monitor
from app.services.provider_strategy import GroupRateResult, provider_registry


class FakeProvider:
    async def fetch_group_catalog(self, platform: RelayPlatform):
        return None

    async def fetch_group_rate(
        self,
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        return GroupRateResult(rate_multiplier=0.25, rpm_limit=120)


def make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_rate_monitor_persists_configured_group_snapshot_without_catalog(monkeypatch) -> None:
    monkeypatch.setitem(provider_registry._strategies, "fake", FakeProvider())
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Fake",
            base_url="https://example.com",
            provider_type="fake",
            rate_cron="*/5 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        group = PlatformGroupMonitor(
            platform_id=platform.id,
            name="codex",
            external_group_id="codex",
            enabled=True,
        )
        db.add(group)
        db.commit()

        asyncio.run(run_platform_rate_monitor(db, platform.id))

        snapshots = db.scalars(select(GroupRateSnapshot)).all()
        assert len(snapshots) == 1
        assert snapshots[0].group_monitor_id == group.id
        assert snapshots[0].rate_multiplier == 0.25
        assert snapshots[0].rpm_limit == 120

        refreshed_group = db.get(PlatformGroupMonitor, group.id)
        assert refreshed_group is not None
        assert refreshed_group.rate_multiplier == 0.25
        assert refreshed_group.rpm_limit == 120
        assert refreshed_group.checked_at is not None
    finally:
        db.close()
