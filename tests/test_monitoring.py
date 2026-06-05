import asyncio
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models.all  # noqa: F401
from app.api.platforms import build_account_balance_points
from app.core.database import Base
from app.models.monitor import PlatformAccountMonitor, PlatformGroupMonitor
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


def test_account_balance_history_points_use_real_snapshots_only() -> None:
    first_at = datetime(2026, 6, 5, 9, 30)
    second_at = datetime(2026, 6, 5, 9, 40)

    points = build_account_balance_points(
        [
            SimpleNamespace(created_at=first_at, balance=10.0, quota_used=1.0, quota_limit=20.0),
            SimpleNamespace(created_at=second_at, balance=9.5, quota_used=1.5, quota_limit=20.0),
        ]
    )

    assert points == [
        {
            "at": first_at,
            "balance": 10.0,
            "quota_used": 1.0,
            "quota_limit": 20.0,
        },
        {
            "at": second_at,
            "balance": 9.5,
            "quota_used": 1.5,
            "quota_limit": 20.0,
        },
    ]


def test_account_monitor_key_summaries_round_trip() -> None:
    account = PlatformAccountMonitor(
        platform_id=1,
        name="Main",
        external_account_id="user@example.com",
    )

    account.key_summaries = (
        {"id": "101", "name": "prod-key", "group_id": "7", "group_name": "codex"},
    )

    assert account.key_summaries == [
        {"id": "101", "name": "prod-key", "group_id": "7", "group_name": "codex"},
    ]

    account.key_summaries_json = "not json"
    assert account.key_summaries == []
