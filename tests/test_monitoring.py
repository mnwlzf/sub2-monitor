import asyncio
import sys
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models.all  # noqa: F401
import app.services.notification as notification_service
from app.api.platforms import (
    attach_today_quota_usage,
    build_account_balance_points,
    clear_platform_error,
    dashboard,
    get_embedded_histories,
    list_platform_details,
)
from app.core.database import Base
from app.core.config import Sub2APIDatabaseSettings
from app.core.security import encrypt_secret
from app.models.monitor import PlatformAccountMonitor, PlatformGroupMonitor
from app.models.notification import NotificationRecipient, NotificationSetting
from app.models.platform import PlatformStatus, RelayPlatform
from app.models.snapshot import (
    AccountBalanceSnapshot,
    DiscoveredChannelRateSnapshot,
    GroupRateSnapshot,
    PlatformSnapshot,
)
from app.schemas.platform import PlatformErrorClearRequest
from app.services.monitoring import (
    ModelFirstTokenResult,
    Sub2APIModelTestAccount,
    load_sub2api_model_test_account,
    measure_platform_model_first_token_ms as real_measure_platform_model_first_token_ms,
    run_platform_balance_monitor,
    run_platform_monitor,
    run_platform_rate_monitor,
    sync_key_group_monitors,
)
from app.services.notification import send_mail
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


class MutableBalanceProvider(FakeBalanceProvider):
    def __init__(self, balance: float) -> None:
        self.balance = balance

    async def fetch_account_balance(
        self,
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        return AccountBalanceResult(balance=self.balance)


class EmptyMessageError(Exception):
    def __str__(self) -> str:
        return ""


class EmptyExceptionBalanceProvider(FakeBalanceProvider):
    async def fetch_account_balance(
        self,
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        raise EmptyMessageError()


class EmptyHttpxExceptionBalanceProvider(FakeBalanceProvider):
    async def fetch_account_balance(
        self,
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        request = httpx.Request("GET", "https://www.kldai.cc/api/v1/auth/login")
        raise httpx.ConnectTimeout("", request=request)


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


class MutableCatalogProvider(FakeCatalogProvider):
    def __init__(self, groups: list[DiscoveredGroupRateResult]) -> None:
        self.groups = groups

    async def fetch_group_catalog(self, platform: RelayPlatform):
        return self.groups

    async def fetch_key_group_catalog(self, platform: RelayPlatform):
        return None

    async def fetch_group_rate(
        self,
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        return GroupRateResult()


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


class FakeNewApiUnifiedProvider:
    def __init__(
        self,
        account_error: str | None = None,
        channel_error: str | None = None,
    ) -> None:
        self.account_error = account_error
        self.channel_error = channel_error
        self.balance_accounts: list[str] = []
        self.group_catalog_calls = 0
        self.channel_catalog_calls = 0

    async def fetch_account_balance(
        self,
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        self.balance_accounts.append(account.name)
        if self.account_error:
            return AccountBalanceResult(error=self.account_error)
        return AccountBalanceResult(
            balance=10.0,
            key_summaries=(
                {"id": f"key-{account.id}", "name": account.name, "group_id": "7", "group_name": "codex"},
            ),
        )

    async def fetch_channel_catalog(self, platform: RelayPlatform):
        self.channel_catalog_calls += 1
        if self.channel_error:
            raise ValueError(self.channel_error)
        return [
            DiscoveredChannelRateResult(
                external_channel_id="1",
                name="OpenAI Official",
                rate_multiplier=2.5,
            )
        ]

    async def fetch_group_catalog(self, platform: RelayPlatform):
        self.group_catalog_calls += 1
        return [
            DiscoveredGroupRateResult(
                external_group_id="7",
                name="codex",
                rate_multiplier=0.12,
            )
        ]

    async def fetch_group_rate(
        self,
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        return GroupRateResult(rate_multiplier=0.12)

    @staticmethod
    def is_insufficient_privileges_message(message: str) -> bool:
        return "insufficient privileges" in message.lower()


class FlakyNewApiUnifiedProvider(FakeNewApiUnifiedProvider):
    def __init__(self, failures_before_success: int) -> None:
        super().__init__()
        self.failures_before_success = failures_before_success

    async def fetch_group_catalog(self, platform: RelayPlatform):
        self.group_catalog_calls += 1
        if self.group_catalog_calls <= self.failures_before_success:
            raise ValueError("temporary group catalog failure")
        return [
            DiscoveredGroupRateResult(
                external_group_id="7",
                name="codex",
                rate_multiplier=0.12,
            )
        ]


def make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


@pytest.fixture(autouse=True)
def no_monitor_retry_delay(monkeypatch) -> None:
    monkeypatch.setattr("app.services.monitoring.MONITOR_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr("app.services.monitoring.measure_platform_connect_latency_ms", _fake_connect_latency)
    monkeypatch.setattr("app.services.monitoring.measure_platform_model_first_token_ms", _fake_first_token)


async def _fake_connect_latency(platform: RelayPlatform) -> int:
    return 42


async def _fake_first_token(platform: RelayPlatform) -> SimpleNamespace:
    if not platform.model_test_model:
        return SimpleNamespace(first_token_ms=None, error=None)
    return SimpleNamespace(first_token_ms=123, error=None)


def test_today_quota_usage_is_attached_to_dashboard_platform_and_accounts() -> None:
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Usage Today",
            base_url="https://example.com",
            provider_type="fake",
            rate_cron="*/5 * * * *",
            balance_cron="*/10 * * * *",
            recharge_amount=1,
            received_amount=2,
            model_test_model="gpt-4o-mini",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        account_a = PlatformAccountMonitor(
            platform_id=platform.id,
            name="A",
            external_account_id="a",
            enabled=True,
        )
        account_b = PlatformAccountMonitor(
            platform_id=platform.id,
            name="B",
            external_account_id="b",
            enabled=True,
        )
        db.add_all([account_a, account_b])
        db.flush()
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        db.add_all(
            [
                AccountBalanceSnapshot(
                    platform_id=platform.id,
                    account_monitor_id=account_a.id,
                    quota_used=10,
                    created_at=today.replace(hour=9),
                ),
                AccountBalanceSnapshot(
                    platform_id=platform.id,
                    account_monitor_id=account_a.id,
                    quota_used=13.5,
                    created_at=today.replace(hour=10),
                ),
                AccountBalanceSnapshot(
                    platform_id=platform.id,
                    account_monitor_id=account_b.id,
                    quota_used=5,
                    created_at=today.replace(hour=9),
                ),
                AccountBalanceSnapshot(
                    platform_id=platform.id,
                    account_monitor_id=account_b.id,
                    quota_used=8,
                    created_at=today.replace(hour=10),
                ),
            ]
        )
        db.commit()
        db.refresh(platform)

        attach_today_quota_usage(db, [platform])

        assert platform.today_quota_used == 6.5
        assert platform.today_actual_used == 3.25
        assert account_a.today_quota_used == 3.5
        assert account_a.today_actual_used == 1.75
        assert account_b.today_quota_used == 3
        assert account_b.today_actual_used == 1.5
        stats = dashboard(db)
        assert stats.today_quota_used == 6.5
        assert stats.today_actual_used == 3.25
    finally:
        db.close()


def test_clear_platform_error_clears_platform_status_and_account_error() -> None:
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Broken",
            base_url="https://relay.example.com",
            provider_type="fake",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.degraded,
            last_error="platform failed",
        )
        db.add(platform)
        db.flush()
        account = PlatformAccountMonitor(
            platform_id=platform.id,
            name="Account",
            external_account_id="account",
            enabled=True,
            last_error="account failed",
        )
        db.add(account)
        db.commit()

        clear_platform_error(
            PlatformErrorClearRequest(source="platform", target_id=platform.id),
            db=db,
        )
        clear_platform_error(
            PlatformErrorClearRequest(source="account", target_id=account.id),
            db=db,
        )

        db.refresh(platform)
        db.refresh(account)
        assert platform.last_error is None
        assert platform.status == PlatformStatus.healthy
        assert account.last_error is None
    finally:
        db.close()


def test_embedded_histories_batches_balances_and_rates() -> None:
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Embedded History",
            base_url="https://example.com",
            provider_type="fake",
            rate_cron="*/30 * * * *",
            balance_cron="*/10 * * * *",
            recharge_amount=2,
            received_amount=1,
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        account = PlatformAccountMonitor(
            platform_id=platform.id,
            name="Primary",
            external_account_id="primary",
            enabled=True,
        )
        group = PlatformGroupMonitor(
            platform_id=platform.id,
            name="codex",
            external_group_id="7",
            enabled=True,
        )
        db.add_all([account, group])
        db.flush()
        now = datetime.now()
        db.add_all(
            [
                AccountBalanceSnapshot(
                    platform_id=platform.id,
                    account_monitor_id=account.id,
                    balance=12.5,
                    created_at=now,
                ),
                GroupRateSnapshot(
                    platform_id=platform.id,
                    group_monitor_id=group.id,
                    rate_multiplier=0.25,
                    rpm_limit=120,
                    created_at=now,
                ),
                PlatformSnapshot(
                    platform_id=platform.id,
                    status=PlatformStatus.healthy,
                    connect_latency_ms=42,
                    model_first_token_ms=123,
                    created_at=now,
                ),
            ]
        )
        db.commit()

        histories = get_embedded_histories([platform.id], db=db)

        assert histories.balances[platform.id][0].account_name == "Primary"
        assert histories.balances[platform.id][0].points[-1].balance == 12.5
        assert histories.rates[platform.id][0].group_name == "codex"
        latest_rate = [point for point in histories.rates[platform.id][0].points if point.rate_multiplier is not None]
        assert latest_rate[-1].rate_multiplier == 0.25
        assert latest_rate[-1].effective_rate_multiplier == 0.5
        first_token_series = histories.first_tokens[platform.id]
        assert first_token_series.platform_name == "Embedded History"
        assert first_token_series.points[-1].model_first_token_ms == 123
        assert first_token_series.points[-1].connect_latency_ms == 42
    finally:
        db.close()


def test_platform_details_list_batches_detail_payloads() -> None:
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Detail Batch",
            base_url="https://detail.example.com",
            provider_type="fake",
            rate_cron="*/30 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        db.add_all(
            [
                PlatformAccountMonitor(
                    platform_id=platform.id,
                    name="Primary",
                    external_account_id="primary",
                    enabled=True,
                ),
                PlatformGroupMonitor(
                    platform_id=platform.id,
                    name="codex",
                    external_group_id="7",
                    enabled=True,
                ),
            ]
        )
        db.commit()

        details = list_platform_details(db=db)
        histories = get_embedded_histories(db=db)

        assert len(details) == 1
        assert details[0].name == "Detail Batch"
        assert len(details[0].account_monitors) == 1
        assert len(details[0].group_monitors) == 1
        assert platform.id in histories.balances
        assert platform.id in histories.rates
        assert platform.id in histories.first_tokens
    finally:
        db.close()


def test_load_sub2api_model_test_account_uses_first_matching_account(monkeypatch) -> None:
    execute_calls: list[tuple[str, object]] = []

    class StubCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params):
            execute_calls.append((sql, params))

        def fetchone(self):
            return (
                10,
                "Account A",
                {"base_url": "https://relay.example.com/", "api_key": "sk-account-a"},
                "https://relay.example.com",
            )

    class StubConnection:
        read_only = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def cursor(self):
            return StubCursor()

    class StubPsycopg:
        @staticmethod
        def connect(*args, **kwargs):
            assert kwargs["connect_timeout"] == 5
            return StubConnection()

    monkeypatch.setitem(sys.modules, "psycopg", StubPsycopg)
    monkeypatch.setattr(
        "app.services.monitoring.get_settings",
        lambda: SimpleNamespace(
            sub2api=SimpleNamespace(
                database=Sub2APIDatabaseSettings(
                    host="postgres",
                    user="sub2api",
                    password="secret",
                    dbname="sub2api",
                )
            )
        ),
    )
    platform = RelayPlatform(
        id=1,
        name="Relay",
        base_url="https://relay.example.com/",
        provider_type="fake",
        rate_cron="*/10 * * * *",
        balance_cron="*/10 * * * *",
        status=PlatformStatus.unknown,
    )

    account, error = load_sub2api_model_test_account(platform)

    assert error is None
    assert account == Sub2APIModelTestAccount(
        account_id=10,
        account_name="Account A",
        api_key="sk-account-a",
        matched_base_url="https://relay.example.com",
    )
    sql, params = execute_calls[0]
    assert "ORDER BY id ASC" in sql
    assert "LIMIT 1" in sql
    assert params == {"base_url": "https://relay.example.com"}


def test_model_first_token_uses_sub2api_account_api_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class StubStream:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"o"}}]}'

    class StubAsyncClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = kwargs["headers"]
            captured["json"] = kwargs["json"]
            return StubStream()

    monkeypatch.setattr("app.services.monitoring.httpx.AsyncClient", StubAsyncClient)
    monkeypatch.setattr(
        "app.services.monitoring.load_sub2api_model_test_account",
        lambda platform: (
            Sub2APIModelTestAccount(
                account_id=10,
                account_name="Account A",
                api_key="sk-account-a",
                matched_base_url="https://relay.example.com",
            ),
            None,
        ),
    )
    platform = RelayPlatform(
        id=1,
        name="Relay",
        base_url="https://relay.example.com",
        provider_type="fake",
        api_key_encrypted=encrypt_secret("sk-platform"),
        auth_header_name="Authorization",
        auth_header_prefix="Bearer",
        model_test_model="gpt-4o-mini",
        rate_cron="*/10 * * * *",
        balance_cron="*/10 * * * *",
        status=PlatformStatus.unknown,
    )

    result: ModelFirstTokenResult = asyncio.run(real_measure_platform_model_first_token_ms(platform))

    assert result.error is None
    assert result.first_token_ms is not None
    assert captured["url"] == "https://relay.example.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-account-a"
    assert captured["json"] == {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }


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
            model_test_model="gpt-4o-mini",
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
        refreshed_platform = db.get(RelayPlatform, platform.id)
        assert refreshed_platform is not None
        assert refreshed_platform.connect_latency_ms == 42
        assert refreshed_platform.model_first_token_ms == 123
        platform_snapshots = db.scalars(select(PlatformSnapshot)).all()
        assert len(platform_snapshots) == 1
        assert platform_snapshots[0].connect_latency_ms == 42
        assert platform_snapshots[0].model_first_token_ms == 123
    finally:
        db.close()


def test_rate_monitor_sends_email_when_configured_group_rate_changes(monkeypatch) -> None:
    monkeypatch.setitem(provider_registry._strategies, "fake", FakeProvider())
    sent_messages: list[tuple[list[str], str, str]] = []

    def fake_send_mail(setting, recipients, subject: str, body: str) -> None:
        sent_messages.append(([recipient.email for recipient in recipients], subject, body))

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
            )
        )
        db.add(
            NotificationRecipient(
                name="Ops",
                email="ops@example.com",
                enabled=True,
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
        recipients, subject, body = sent_messages[0]
        assert recipients == ["ops@example.com"]
        assert "Fake" in subject
        assert "codex" in body
        assert "0.1 -> 0.25" in body
    finally:
        db.close()


def test_rate_monitor_sends_email_when_discovered_groups_are_added_or_removed(monkeypatch) -> None:
    provider = MutableCatalogProvider(
        [
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
    )
    monkeypatch.setitem(provider_registry._strategies, "mutable-catalog", provider)
    sent_messages: list[tuple[list[str], str, str]] = []

    def fake_send_mail(setting, recipients, subject: str, body: str) -> None:
        sent_messages.append(([recipient.email for recipient in recipients], subject, body))

    monkeypatch.setattr(notification_service, "send_mail", fake_send_mail)
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Catalog Alert",
            base_url="https://example.com",
            provider_type="mutable-catalog",
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
            )
        )
        db.add(NotificationRecipient(name="Ops", email="ops@example.com", enabled=True))
        db.commit()

        asyncio.run(run_platform_rate_monitor(db, platform.id))
        assert sent_messages == []

        provider.groups = [
            DiscoveredGroupRateResult(
                external_group_id="8",
                name="premium",
                rate_multiplier=0.8,
            ),
            DiscoveredGroupRateResult(
                external_group_id="9",
                name="enterprise",
                rate_multiplier=1.2,
                rpm_limit=30,
            ),
        ]
        asyncio.run(run_platform_rate_monitor(db, platform.id))

        assert len(sent_messages) == 1
        recipients, subject, body = sent_messages[0]
        assert recipients == ["ops@example.com"]
        assert "分组变化" in subject
        assert "分组新增/减少" in body
        assert "新增 enterprise (9)" in body
        assert "减少 codex (7)" in body
        assert "倍率: 1.2，RPM: 30" in body
        assert "倍率: 0.12，RPM: 60" in body
    finally:
        db.close()


def test_rate_monitor_skips_email_when_group_rate_notification_disabled(monkeypatch) -> None:
    monkeypatch.setitem(provider_registry._strategies, "fake", FakeProvider())
    sent_messages: list[tuple[list[str], str, str]] = []

    def fake_send_mail(setting, recipients, subject: str, body: str) -> None:
        sent_messages.append(([recipient.email for recipient in recipients], subject, body))

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
                notify_group_rate_changes=False,
            )
        )
        db.add(NotificationRecipient(name="Ops", email="ops@example.com", enabled=True))
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

        assert sent_messages == []
        setting = db.get(NotificationSetting, 1)
        assert setting is not None
        assert setting.last_error is None
    finally:
        db.close()


def test_notification_error_lists_missing_smtp_fields() -> None:
    setting = NotificationSetting(enabled=False, smtp_port=587)
    recipient = NotificationRecipient(name="Ops", email="ops@example.com", enabled=True)

    try:
        send_mail(setting, [recipient], "Subject", "Body")
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("send_mail should fail when SMTP config is incomplete")

    assert "未启用邮件通知" in message
    assert "未配置 SMTP 主机" in message
    assert "未配置发件人邮箱" in message


def test_balance_monitor_sends_low_balance_email_at_most_three_times(monkeypatch) -> None:
    provider = MutableBalanceProvider(balance=4.5)
    monkeypatch.setitem(provider_registry._strategies, "mutable-balance", provider)
    sent_messages: list[tuple[list[str], str, str]] = []

    def fake_send_mail(setting, recipients, subject: str, body: str) -> None:
        sent_messages.append(([recipient.email for recipient in recipients], subject, body))

    monkeypatch.setattr(notification_service, "send_mail", fake_send_mail)
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Balance Alert",
            base_url="https://example.com",
            provider_type="mutable-balance",
            rate_cron="*/5 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
            low_balance_threshold=5.0,
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
                notify_low_balance=True,
            )
        )
        db.add(NotificationRecipient(name="Ops", email="ops@example.com", enabled=True))
        db.add(
            PlatformAccountMonitor(
                platform_id=platform.id,
                name="main",
                external_account_id="me",
                enabled=True,
            )
        )
        db.commit()

        for _ in range(4):
            asyncio.run(run_platform_balance_monitor(db, platform.id))

        assert len(sent_messages) == 3
        assert all(recipients == ["ops@example.com"] for recipients, _, _ in sent_messages)
        assert all("额度不足提醒" in subject for _, subject, _ in sent_messages)
        assert "当前余额：4.5" in sent_messages[0][2]
        refreshed = db.get(RelayPlatform, platform.id)
        assert refreshed is not None
        assert refreshed.low_balance_notify_count == 3
    finally:
        db.close()


def test_balance_monitor_resets_low_balance_notification_count_after_recovery(monkeypatch) -> None:
    provider = MutableBalanceProvider(balance=4.5)
    monkeypatch.setitem(provider_registry._strategies, "mutable-balance", provider)
    sent_messages: list[tuple[list[str], str, str]] = []

    def fake_send_mail(setting, recipients, subject: str, body: str) -> None:
        sent_messages.append(([recipient.email for recipient in recipients], subject, body))

    monkeypatch.setattr(notification_service, "send_mail", fake_send_mail)
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Balance Recovery",
            base_url="https://example.com",
            provider_type="mutable-balance",
            rate_cron="*/5 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
            low_balance_threshold=5.0,
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
                notify_low_balance=True,
            )
        )
        db.add(NotificationRecipient(name="Ops", email="ops@example.com", enabled=True))
        db.add(
            PlatformAccountMonitor(
                platform_id=platform.id,
                name="main",
                external_account_id="me",
                enabled=True,
            )
        )
        db.commit()

        asyncio.run(run_platform_balance_monitor(db, platform.id))
        provider.balance = 5.0
        asyncio.run(run_platform_balance_monitor(db, platform.id))
        provider.balance = 4.0
        asyncio.run(run_platform_balance_monitor(db, platform.id))

        assert len(sent_messages) == 2
        refreshed = db.get(RelayPlatform, platform.id)
        assert refreshed is not None
        assert refreshed.low_balance_notify_count == 1
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


def test_key_group_sync_does_not_rewrite_existing_group_id() -> None:
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Legacy Group",
            base_url="https://example.com",
            provider_type="fake",
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
            {
                "id": "811",
                "name": "codex-key",
                "group_id": "codex（特价分组-4）",
                "group_name": "codex（特价分组-4）",
            },
        )
        db.add(account)
        legacy_group = PlatformGroupMonitor(
            platform_id=platform.id,
            name="codex（特价分组-4）",
            external_group_id="codex",
            enabled=True,
            rate_multiplier=0.08,
        )
        db.add(legacy_group)
        db.flush()

        sync_key_group_monitors(db, platform)

        groups = db.scalars(select(PlatformGroupMonitor)).all()
        assert len(groups) == 2
        by_external_id = {group.external_group_id: group for group in groups}
        assert by_external_id["codex"].id == legacy_group.id
        assert by_external_id["codex"].name == "codex（特价分组-4）"
        assert by_external_id["codex"].rate_multiplier == 0.08
        assert by_external_id["codex（特价分组-4）"].name == "codex（特价分组-4）"
        assert by_external_id["codex（特价分组-4）"].enabled is True
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


def test_newapi_unified_monitor_collects_balances_and_rates_once(monkeypatch) -> None:
    provider = FakeNewApiUnifiedProvider()
    monkeypatch.setitem(provider_registry._strategies, "newapi", provider)
    db = make_session()
    try:
        platform = RelayPlatform(
            name="NewApi Unified",
            base_url="https://newapi.example.com",
            provider_type="newapi",
            site_strategy="generic",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        db.add_all(
            [
                PlatformAccountMonitor(
                    platform_id=platform.id,
                    name="Account A",
                    external_account_id="a",
                    enabled=True,
                ),
                PlatformAccountMonitor(
                    platform_id=platform.id,
                    name="Account B",
                    external_account_id="b",
                    enabled=True,
                ),
            ]
        )
        db.commit()

        asyncio.run(run_platform_monitor(db, platform.id))

        assert provider.balance_accounts == ["Account A", "Account B"]
        assert provider.group_catalog_calls == 1
        assert provider.channel_catalog_calls == 1
        refreshed = db.get(RelayPlatform, platform.id)
        assert refreshed is not None
        assert refreshed.balance == 20.0
        assert refreshed.balance_next_run_at == refreshed.rate_next_run_at
        assert len(refreshed.discovered_channel_rates) == 1
        assert len(refreshed.discovered_group_rates) == 1
    finally:
        db.close()


def test_newapi_account_monitor_persists_last_proxy_url_for_any_site_strategy(monkeypatch) -> None:
    provider = FakeNewApiUnifiedProvider()
    monkeypatch.setitem(provider_registry._strategies, "newapi", provider)
    monkeypatch.setattr(
        "app.services.monitoring.load_platform_proxy_urls",
        lambda database, base_url: [
            "socks5://user:secret@127.0.0.1:1080",
            "http://proxy.example.com:8080",
        ],
    )
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Yunjin Proxy Debug",
            base_url="https://sub2api.example.com",
            provider_type="newapi",
            site_strategy="yunjin",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        db.add_all(
            [
                PlatformAccountMonitor(
                    platform_id=platform.id,
                    name="Account A",
                    external_account_id="a",
                    enabled=True,
                ),
                PlatformAccountMonitor(
                    platform_id=platform.id,
                    name="Account B",
                    external_account_id="b",
                    enabled=True,
                ),
            ]
        )
        db.commit()

        asyncio.run(run_platform_monitor(db, platform.id))

        accounts = db.scalars(
            select(PlatformAccountMonitor).order_by(PlatformAccountMonitor.id.asc())
        ).all()
        assert [account.last_proxy_url for account in accounts] == [
            "socks5://user:<masked>@127.0.0.1:1080",
            "http://proxy.example.com:8080",
        ]
    finally:
        db.close()


def test_newapi_unified_monitor_without_accounts_collects_rates_only(monkeypatch) -> None:
    provider = FakeNewApiUnifiedProvider()
    monkeypatch.setitem(provider_registry._strategies, "newapi", provider)
    db = make_session()
    try:
        platform = RelayPlatform(
            name="NewApi Rates Only",
            base_url="https://newapi.example.com",
            provider_type="newapi",
            site_strategy="generic",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.commit()

        asyncio.run(run_platform_monitor(db, platform.id))

        assert provider.balance_accounts == []
        assert provider.group_catalog_calls == 1
        assert provider.channel_catalog_calls == 1
        refreshed = db.get(RelayPlatform, platform.id)
        assert refreshed is not None
        assert refreshed.balance is None
        assert refreshed.balance_last_run_at is None
        assert refreshed.rate_last_run_at is not None
    finally:
        db.close()


def test_run_platform_monitor_retries_until_public_monitor_succeeds(monkeypatch) -> None:
    provider = FlakyNewApiUnifiedProvider(failures_before_success=2)
    monkeypatch.setitem(provider_registry._strategies, "newapi", provider)

    async def no_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr("app.services.monitoring.asyncio.sleep", no_sleep)
    db = make_session()
    try:
        platform = RelayPlatform(
            name="NewApi Retry",
            base_url="https://newapi.example.com",
            provider_type="newapi",
            site_strategy="generic",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.commit()

        result = asyncio.run(run_platform_monitor(db, platform.id))

        assert provider.group_catalog_calls == 3
        assert result.status == PlatformStatus.healthy
        assert result.last_error is None
        refreshed = db.get(RelayPlatform, platform.id)
        assert refreshed is not None
        assert refreshed.status == PlatformStatus.healthy
        assert refreshed.last_error is None
        assert len(refreshed.discovered_group_rates) == 1
    finally:
        db.close()


def test_newapi_channel_catalog_insufficient_privileges_does_not_degrade_platform(monkeypatch) -> None:
    provider = FakeNewApiUnifiedProvider(
        channel_error="Unauthorized, insufficient privileges",
    )
    monkeypatch.setitem(provider_registry._strategies, "newapi", provider)
    db = make_session()
    try:
        platform = RelayPlatform(
            name="NewApi Channel Permission",
            base_url="https://relayai.tech/",
            provider_type="newapi",
            site_strategy="generic",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.commit()

        asyncio.run(run_platform_monitor(db, platform.id))

        assert provider.channel_catalog_calls == 1
        assert provider.group_catalog_calls == 1
        refreshed = db.get(RelayPlatform, platform.id)
        assert refreshed is not None
        assert refreshed.status == PlatformStatus.healthy
        assert refreshed.last_error is None
        assert len(refreshed.discovered_group_rates) == 1
        assert len(refreshed.discovered_channel_rates) == 0
    finally:
        db.close()


def test_newapi_account_error_identifies_account(monkeypatch) -> None:
    provider = FakeNewApiUnifiedProvider(account_error="login returned HTTP 429")
    monkeypatch.setitem(provider_registry._strategies, "newapi", provider)
    db = make_session()
    try:
        platform = RelayPlatform(
            name="NewApi Account Error",
            base_url="https://newapi.example.com",
            provider_type="newapi",
            site_strategy="generic",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        db.add(
            PlatformAccountMonitor(
                platform_id=platform.id,
                name="Primary",
                external_account_id="user-1",
                username="primary@example.com",
                enabled=True,
            )
        )
        db.commit()

        asyncio.run(run_platform_monitor(db, platform.id))

        account = db.scalar(select(PlatformAccountMonitor))
        assert account is not None
        assert account.last_error == "账号监控失败（Primary / primary@example.com / user-1）：login returned HTTP 429"
        refreshed = db.get(RelayPlatform, platform.id)
        assert refreshed is not None
        assert refreshed.last_error is not None
        assert "Primary / primary@example.com / user-1" in refreshed.last_error
    finally:
        db.close()


def test_balance_monitor_empty_exception_message_uses_exception_type(monkeypatch) -> None:
    provider = EmptyExceptionBalanceProvider()
    monkeypatch.setitem(provider_registry._strategies, "empty-exception-balance", provider)
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Empty Exception",
            base_url="https://example.com",
            provider_type="empty-exception-balance",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        db.add(
            PlatformAccountMonitor(
                platform_id=platform.id,
                name="Primary",
                external_account_id="user-1",
                enabled=True,
            )
        )
        db.commit()

        asyncio.run(run_platform_balance_monitor(db, platform.id))

        account = db.scalar(select(PlatformAccountMonitor))
        assert account is not None
        assert account.last_error == "账号监控失败（Primary / user-1）：EmptyMessageError: EmptyMessageError()"
        refreshed = db.get(RelayPlatform, platform.id)
        assert refreshed is not None
        assert refreshed.last_error == (
            "采集尝试 3 次后仍失败：账号监控失败（Primary / user-1）：EmptyMessageError: EmptyMessageError()"
        )
    finally:
        db.close()


def test_balance_monitor_empty_httpx_exception_includes_request_url(monkeypatch) -> None:
    provider = EmptyHttpxExceptionBalanceProvider()
    monkeypatch.setitem(provider_registry._strategies, "empty-httpx-exception-balance", provider)
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Empty HTTPX Exception",
            base_url="https://www.kldai.cc",
            provider_type="empty-httpx-exception-balance",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        db.add(
            PlatformAccountMonitor(
                platform_id=platform.id,
                name="Primary",
                external_account_id="user-1",
                enabled=True,
            )
        )
        db.commit()

        asyncio.run(run_platform_balance_monitor(db, platform.id))

        account = db.scalar(select(PlatformAccountMonitor))
        assert account is not None
        assert account.last_error is not None
        assert "ConnectTimeout" in account.last_error
        assert "request=GET https://www.kldai.cc/api/v1/auth/login" in account.last_error
        refreshed = db.get(RelayPlatform, platform.id)
        assert refreshed is not None
        assert refreshed.last_error == f"采集尝试 3 次后仍失败：{account.last_error}"
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
