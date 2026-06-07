import asyncio
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models.all  # noqa: F401
import app.services.notification as notification_service
from app.api.platforms import build_account_balance_points
from app.core.database import Base
from app.models.monitor import PlatformAccountMonitor, PlatformGroupMonitor
from app.models.notification import NotificationSetting
from app.models.platform import PlatformStatus, RelayPlatform
from app.models.snapshot import DiscoveredChannelRateSnapshot, GroupRateSnapshot
from app.services.monitoring import run_platform_balance_monitor, run_platform_rate_monitor
from app.services.provider_strategy import (
    AccountBalanceResult,
    DiscoveredChannelRateResult,
    DiscoveredGroupRateResult,
    GroupRateResult,
    KeyGroupMonitorResult,
    provider_registry,
)


class FakeProvider:
    async def fetch_group_catalog(self, platform: RelayPlatform):
        return None

    async def fetch_group_rate(
        self,
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        return GroupRateResult(rate_multiplier=0.25, rpm_limit=120)


class FakeBalanceProvider:
    async def fetch_account_balance(
        self,
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        return AccountBalanceResult(
            balance=12.5,
            quota_used=3.5,
            quota_limit=20.0,
            key_summaries=(
                {"id": "101", "name": "prod-key", "group_id": "7", "group_name": "codex"},
                {"id": "102", "name": "ungrouped-key", "group_id": None, "group_name": None},
            ),
        )

    async def fetch_group_catalog(self, platform: RelayPlatform):
        return None

    async def fetch_group_rate(
        self,
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        return GroupRateResult()


class FakeCatalogProvider:
    async def fetch_account_balance(
        self,
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        return AccountBalanceResult()

    async def fetch_group_catalog(self, platform: RelayPlatform):
        return [
            DiscoveredGroupRateResult(
                external_group_id="7",
                name="codex",
                rate_multiplier=0.12,
                rpm_limit=60,
            ),
            DiscoveredGroupRateResult(
                external_group_id="8",
                name="premium",
                rate_multiplier=0.8,
            ),
        ]

    async def fetch_key_group_catalog(self, platform: RelayPlatform):
        return [KeyGroupMonitorResult(external_group_id="7", name="codex")]

    async def fetch_group_rate(
        self,
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        return GroupRateResult(rate_multiplier=0.99)


class FakeChannelCatalogProvider:
    async def fetch_channel_catalog(self, platform: RelayPlatform):
        return [
            DiscoveredChannelRateResult(
                external_channel_id="1",
                name="OpenAI Official",
                base_url="https://api.openai.com",
                status="启用",
                rate_multiplier=2.5,
                model_rates={"gpt-4o": 2.0, "gpt-4o-mini": 3.0},
            )
        ]

    async def fetch_group_catalog(self, platform: RelayPlatform):
        return None

    async def fetch_group_rate(
        self,
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        return GroupRateResult()


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


def test_rate_monitor_sends_email_when_configured_group_rate_changes(monkeypatch) -> None:
    monkeypatch.setitem(provider_registry._strategies, "fake", FakeProvider())
    sent_messages: list[tuple[str, str]] = []

    def fake_send_mail(setting, subject: str, body: str) -> None:
        sent_messages.append((subject, body))

    monkeypatch.setattr(notification_service, "send_mail", fake_send_mail)
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
        db.add(
            NotificationSetting(
                id=1,
                enabled=True,
                smtp_host="smtp.example.com",
                smtp_port=587,
                smtp_username="bot@example.com",
                from_email="bot@example.com",
                recipient_email="ops@example.com",
            )
        )
        group = PlatformGroupMonitor(
            platform_id=platform.id,
            name="codex",
            external_group_id="codex",
            enabled=True,
            rate_multiplier=0.1,
        )
        db.add(group)
        db.commit()

        asyncio.run(run_platform_rate_monitor(db, platform.id))

        assert len(sent_messages) == 1
        subject, body = sent_messages[0]
        assert "Fake" in subject
        assert "codex" in body
        assert "0.1 -> 0.25" in body
    finally:
        db.close()


def test_balance_monitor_adds_key_group_as_group_monitor(monkeypatch) -> None:
    monkeypatch.setitem(provider_registry._strategies, "fake-balance", FakeBalanceProvider())
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Fake Balance",
            base_url="https://example.com",
            provider_type="fake-balance",
            rate_cron="*/5 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        db.add(
            PlatformAccountMonitor(
                platform_id=platform.id,
                name="Main",
                external_account_id="user@example.com",
                enabled=True,
            )
        )
        db.commit()

        asyncio.run(run_platform_balance_monitor(db, platform.id))

        groups = db.scalars(select(PlatformGroupMonitor)).all()
        assert len(groups) == 1
        assert groups[0].external_group_id == "7"
        assert groups[0].name == "codex"
        assert groups[0].enabled is True
    finally:
        db.close()


def test_rate_monitor_records_key_group_from_stored_summaries(monkeypatch) -> None:
    monkeypatch.setitem(provider_registry._strategies, "fake-catalog", FakeCatalogProvider())
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Fake Catalog",
            base_url="https://example.com",
            provider_type="fake-catalog",
            rate_cron="*/5 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        account = PlatformAccountMonitor(
            platform_id=platform.id,
            name="Main",
            external_account_id="user@example.com",
            enabled=True,
        )
        account.key_summaries = (
            {"id": "101", "name": "prod-key", "group_id": "7", "group_name": "codex"},
        )
        db.add(account)
        db.commit()

        asyncio.run(run_platform_rate_monitor(db, platform.id))

        group = db.scalar(select(PlatformGroupMonitor).where(PlatformGroupMonitor.external_group_id == "7"))
        assert group is not None
        assert group.name == "codex"

        snapshots = db.scalars(select(GroupRateSnapshot)).all()
        assert len(snapshots) == 1
        assert snapshots[0].group_monitor_id == group.id
        assert snapshots[0].rate_multiplier == 0.12
    finally:
        db.close()


def test_rate_monitor_fetches_key_group_without_stored_summaries(monkeypatch) -> None:
    monkeypatch.setitem(provider_registry._strategies, "fake-catalog", FakeCatalogProvider())
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Fake Fresh Catalog",
            base_url="https://example.com",
            provider_type="fake-catalog",
            rate_cron="*/5 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        db.add(
            PlatformAccountMonitor(
                platform_id=platform.id,
                name="Main",
                external_account_id="user@example.com",
                enabled=True,
            )
        )
        db.commit()

        asyncio.run(run_platform_rate_monitor(db, platform.id))

        groups = db.scalars(select(PlatformGroupMonitor)).all()
        assert len(groups) == 1
        assert groups[0].external_group_id == "7"
        assert groups[0].name == "codex"
    finally:
        db.close()


def test_rate_monitor_persists_discovered_channel_rates(monkeypatch) -> None:
    monkeypatch.setitem(provider_registry._strategies, "fake-channel-catalog", FakeChannelCatalogProvider())
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Fake Channel Catalog",
            base_url="https://example.com",
            provider_type="fake-channel-catalog",
            rate_cron="*/5 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.commit()

        asyncio.run(run_platform_rate_monitor(db, platform.id))

        refreshed = db.get(RelayPlatform, platform.id)
        assert refreshed is not None
        assert len(refreshed.discovered_channel_rates) == 1
        channel = refreshed.discovered_channel_rates[0]
        assert channel.external_channel_id == "1"
        assert channel.name == "OpenAI Official"
        assert channel.rate_multiplier == 2.5
        assert channel.model_rates == {"gpt-4o": 2.0, "gpt-4o-mini": 3.0}

        snapshots = db.scalars(select(DiscoveredChannelRateSnapshot)).all()
        assert len(snapshots) == 1
        assert snapshots[0].external_channel_id == "1"
        assert snapshots[0].rate_multiplier == 2.5
        assert '"gpt-4o": 2.0' in (snapshots[0].model_rates_json or "")
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
