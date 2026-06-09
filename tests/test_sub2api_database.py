import asyncio
import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models.all  # noqa: F401
from app.api.sub2api import get_sql_log, list_sql_logs
from app.core.config import Sub2APIDatabaseSettings, Sub2APISettings
from app.core.database import Base
from app.core.security import encrypt_secret
from app.models.monitor import PlatformAccountMonitor, PlatformGroupMonitor
from app.models.platform import PlatformStatus, RelayPlatform
from app.models.sub2api import (
    Sub2APIMonitorFailureState,
    Sub2APIMonitorSuspendedAccount,
    Sub2APISQLLog,
)
from app.models.user import User
from app.services.priority_sync import (
    PRIORITY_SYNC_PRIORITY_STEP,
    build_priority_sync_plan,
    refresh_and_sync_sub2api_account_priorities,
    sync_sub2api_account_priorities,
)
from app.services.sub2api_database import create_sql_log, execute_recorded_sub2api_write
from app.services.sub2api_schedulable import (
    record_sub2api_monitor_failure,
    record_sub2api_monitor_result,
    record_sub2api_monitor_success,
)


def make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_create_sql_log_persists_masked_database_and_actor() -> None:
    db = make_session()
    try:
        user = User(username="admin", password_hash="hash")
        db.add(user)
        db.commit()
        db.refresh(user)
        database = Sub2APIDatabaseSettings(
            host="sub2api-postgres",
            user="newapi",
            password="secret-password",
            dbname="sub2api",
        )

        log = create_sql_log(
            db,
            operation="update_user_quota",
            database=database,
            sql_text="update users set quota = %(quota)s where id = %(id)s",
            sql_params={"quota": 100, "id": 7},
            status="succeeded",
            affected_rows=1,
            user=user,
        )

        assert log.id is not None
        assert log.target_database == (
            "postgresql://newapi:<masked>@sub2api-postgres:5432/sub2api?sslmode=disable"
        )
        assert "secret-password" not in log.target_database
        assert json.loads(log.sql_params_json or "{}") == {"quota": 100, "id": 7}
        assert log.executed_by_user_id == user.id
        assert log.executed_by_username == "admin"
    finally:
        db.close()


def test_execute_recorded_sub2api_write_logs_unconfigured_failure() -> None:
    db = make_session()
    try:
        log = execute_recorded_sub2api_write(
            db,
            database=Sub2APIDatabaseSettings(user="", password="", dbname="sub2api"),
            operation="delete_expired_keys",
            sql_text="delete from api_keys where expired = true",
        )

        assert log.status == "failed"
        assert log.error_message == "Sub2API database is not configured"
        assert log.affected_rows is None
    finally:
        db.close()


def test_sql_log_api_lists_and_fetches_logs() -> None:
    db = make_session()
    try:
        database = Sub2APIDatabaseSettings(
            host="sub2api-postgres",
            user="newapi",
            password="secret-password",
            dbname="sub2api",
        )
        failed = create_sql_log(
            db,
            operation="sync_accounts",
            database=database,
            sql_text="update accounts set disabled = true where id = %(id)s",
            sql_params={"id": 1},
            status="failed",
            error_message="permission denied",
        )
        create_sql_log(
            db,
            operation="sync_accounts",
            database=database,
            sql_text="update accounts set disabled = false where id = %(id)s",
            sql_params={"id": 2},
            status="succeeded",
            affected_rows=1,
        )

        page = list_sql_logs(limit=10, offset=0, status="failed", operation=None, db=db)
        detail = get_sql_log(failed.id, db=db)

        assert page.total == 1
        assert page.items[0].id == failed.id
        assert page.items[0].error_message == "permission denied"
        assert detail.id == failed.id
        assert detail.sql_text.startswith("update accounts")
    finally:
        db.close()


def test_priority_sync_plan_uses_lowest_effective_key_group_rate() -> None:
    db = make_session()
    try:
        expensive = RelayPlatform(
            name="Expensive",
            base_url="https://relay-expensive.example.com/",
            provider_type="fake",
            api_key_encrypted=encrypt_secret("sk-expensive"),
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            recharge_amount=2,
            received_amount=1,
            status=PlatformStatus.unknown,
        )
        cheap = RelayPlatform(
            name="Cheap",
            base_url="https://relay-cheap.example.com",
            provider_type="fake",
            api_key_encrypted=encrypt_secret("sk-cheap"),
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            recharge_amount=1,
            received_amount=1,
            status=PlatformStatus.unknown,
        )
        db.add_all([expensive, cheap])
        db.flush()

        expensive_account = PlatformAccountMonitor(
            platform_id=expensive.id,
            name="Expensive Account",
            external_account_id="expensive",
            enabled=True,
        )
        expensive_account.key_summaries = (
            {"id": "101", "name": "expensive-low", "group_id": "7", "group_name": "codex"},
            {"id": "102", "name": "expensive-high", "group_id": "8", "group_name": "premium"},
        )
        cheap_account = PlatformAccountMonitor(
            platform_id=cheap.id,
            name="Cheap Account",
            external_account_id="cheap",
            enabled=True,
        )
        cheap_account.key_summaries = (
            {"id": "201", "name": "cheap-key", "group_id": "9", "group_name": "budget"},
        )
        db.add_all(
            [
                expensive_account,
                cheap_account,
                PlatformGroupMonitor(
                    platform_id=expensive.id,
                    name="codex",
                    external_group_id="7",
                    enabled=True,
                    rate_multiplier=0.1,
                ),
                PlatformGroupMonitor(
                    platform_id=expensive.id,
                    name="premium",
                    external_group_id="8",
                    enabled=True,
                    rate_multiplier=0.3,
                ),
                PlatformGroupMonitor(
                    platform_id=cheap.id,
                    name="budget",
                    external_group_id="9",
                    enabled=True,
                    rate_multiplier=0.05,
                ),
            ]
        )
        db.commit()

        plan = build_priority_sync_plan(db)

        assert [item["platform_name"] for item in plan] == ["Cheap", "Expensive"]
        assert [item["priority"] for item in plan] == [5, 10]
        assert plan[0]["normalized_base_url"] == "https://relay-cheap.example.com"
        assert plan[0]["effective_rate_multiplier"] == 0.05
        assert plan[1]["effective_rate_multiplier"] == 0.2
        assert plan[1]["selected_group"]["external_group_id"] == "7"
    finally:
        db.close()


def test_priority_sync_plan_dedupes_by_base_url_without_api_key() -> None:
    db = make_session()
    try:
        shared_url = "https://relay.example.com/"
        first = RelayPlatform(
            name="First",
            base_url=shared_url,
            provider_type="fake",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        second = RelayPlatform(
            name="Second",
            base_url=shared_url,
            provider_type="fake",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        cheaper_duplicate = RelayPlatform(
            name="Cheaper Duplicate",
            base_url=shared_url,
            provider_type="fake",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add_all([first, second, cheaper_duplicate])
        db.flush()

        for platform, group_id, rate_multiplier in (
            (first, "1", 0.2),
            (second, "2", 0.3),
            (cheaper_duplicate, "3", 0.1),
        ):
            account = PlatformAccountMonitor(
                platform_id=platform.id,
                name=f"{platform.name} Account",
                external_account_id=str(platform.id),
                enabled=True,
            )
            account.key_summaries = (
                {"id": str(platform.id), "name": "key", "group_id": group_id, "group_name": "group"},
            )
            db.add_all(
                [
                    account,
                    PlatformGroupMonitor(
                        platform_id=platform.id,
                        name="group",
                        external_group_id=group_id,
                        enabled=True,
                        rate_multiplier=rate_multiplier,
                    ),
                ]
            )
        db.commit()

        plan = build_priority_sync_plan(db)

        assert [item["platform_name"] for item in plan] == [
            "Cheaper Duplicate",
            "First",
            "Second",
        ]
        assert [item["status"] for item in plan] == ["planned", "skipped", "skipped"]
        assert plan[0]["priority"] == 5
        assert plan[1]["error_message"] == "同一 base_url 已由更低实际倍率平台 Cheaper Duplicate 接管"
        assert plan[2]["error_message"] == "同一 base_url 已由更低实际倍率平台 First 接管"
    finally:
        db.close()


def test_priority_sync_plan_excludes_failed_refresh_platforms_from_sorting() -> None:
    db = make_session()
    try:
        failed = RelayPlatform(
            name="Failed Cheap",
            base_url="https://failed.example.com/",
            provider_type="fake",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        healthy = RelayPlatform(
            name="Healthy Expensive",
            base_url="https://healthy.example.com/",
            provider_type="fake",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add_all([failed, healthy])
        db.flush()

        for platform, group_id, rate_multiplier in (
            (failed, "1", 0.01),
            (healthy, "2", 0.2),
        ):
            account = PlatformAccountMonitor(
                platform_id=platform.id,
                name=f"{platform.name} Account",
                external_account_id=str(platform.id),
                enabled=True,
            )
            account.key_summaries = (
                {"id": str(platform.id), "name": "key", "group_id": group_id, "group_name": "group"},
            )
            db.add_all(
                [
                    account,
                    PlatformGroupMonitor(
                        platform_id=platform.id,
                        name="group",
                        external_group_id=group_id,
                        enabled=True,
                        rate_multiplier=rate_multiplier,
                    ),
                ]
            )
        db.commit()

        plan = build_priority_sync_plan(
            db,
            excluded_platforms={failed.id: "Failed Cheap（https://failed.example.com）：连接超时"},
        )

        assert [item["platform_name"] for item in plan] == ["Healthy Expensive", "Failed Cheap"]
        assert [item["status"] for item in plan] == ["planned", "skipped"]
        assert plan[0]["priority"] == 5
        assert plan[1]["priority"] is None
        assert plan[1]["error_message"] == (
            "本次预采集失败，已从 Priority 排序中剔除："
            "Failed Cheap（https://failed.example.com）：连接超时"
        )
    finally:
        db.close()


def test_priority_sync_refresh_error_names_excluded_platform(monkeypatch) -> None:
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Broken Relay",
            base_url="https://broken.example.com/",
            provider_type="fake",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        account = PlatformAccountMonitor(
            platform_id=platform.id,
            name="Main",
            external_account_id="main",
            enabled=True,
        )
        account.key_summaries = (
            {"id": "101", "name": "main-key", "group_id": "7", "group_name": "codex"},
        )
        db.add_all(
            [
                account,
                PlatformGroupMonitor(
                    platform_id=platform.id,
                    name="codex",
                    external_group_id="7",
                    enabled=True,
                    rate_multiplier=0.08,
                ),
            ]
        )
        db.commit()

        async def fail_monitor(db_arg, platform_id):  # noqa: ANN001
            raise RuntimeError("分组倍率目录读取失败：HTTP 502")

        monkeypatch.setattr(
            "app.services.priority_sync.run_platform_monitor",
            fail_monitor,
        )

        run = asyncio.run(
            refresh_and_sync_sub2api_account_priorities(
                db,
                database=Sub2APIDatabaseSettings(user="", password="", dbname="sub2api"),
            )
        )

        assert run.status == "partial"
        assert run.skipped_items == 1
        assert run.items[0]["platform_name"] == "Broken Relay"
        assert run.items[0]["priority"] is None
        assert "Broken Relay（https://broken.example.com）" in (run.error_message or "")
        assert "分组倍率目录读取失败：HTTP 502" in (run.error_message or "")
        assert "已从本次 Priority 排序中剔除" in (run.error_message or "")
    finally:
        db.close()


def test_priority_sync_updates_priority_through_sub2api_admin_api(monkeypatch) -> None:
    db = make_session()
    calls: list[tuple[list[int], dict[str, object]]] = []

    class FakeAdminClient:
        def __init__(self, settings):  # noqa: ANN001
            self.settings = settings

        async def list_accounts(self):
            return [
                {
                    "id": 101,
                    "name": "matched",
                    "credentials": {"base_url": "https://relay.example.com/"},
                    "extra": {},
                },
                {
                    "id": 102,
                    "name": "other",
                    "credentials": {"base_url": "https://other.example.com"},
                    "extra": {},
                },
            ]

        async def bulk_update_accounts(self, account_ids, updates):  # noqa: ANN001
            ids = list(account_ids)
            calls.append((ids, dict(updates)))
            return {"success": len(ids), "failed": 0, "success_ids": ids, "failed_ids": []}

    monkeypatch.setattr(
        "app.services.priority_sync.Sub2APIAdminClient",
        FakeAdminClient,
    )
    try:
        user = User(username="admin", password_hash="hash")
        platform = RelayPlatform(
            name="Sync Target",
            base_url="https://relay.example.com/",
            provider_type="fake",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add_all([user, platform])
        db.flush()
        account = PlatformAccountMonitor(
            platform_id=platform.id,
            name="Main",
            external_account_id="main",
            enabled=True,
        )
        account.key_summaries = (
            {"id": "101", "name": "main-key", "group_id": "7", "group_name": "codex"},
        )
        db.add_all(
            [
                account,
                PlatformGroupMonitor(
                    platform_id=platform.id,
                    name="codex",
                    external_group_id="7",
                    enabled=True,
                    rate_multiplier=0.08,
                ),
            ]
        )
        db.commit()
        db.refresh(user)

        run = asyncio.run(
            sync_sub2api_account_priorities(
                db,
                database=Sub2APIDatabaseSettings(user="", password="", dbname="sub2api"),
                sub2api_settings=Sub2APISettings(
                    admin_base_url="https://sub2api.example.com",
                    admin_api_key="admin-key",
                ),
                user=user,
            )
        )

        assert PRIORITY_SYNC_PRIORITY_STEP == 5
        assert run.status == "succeeded"
        assert run.total_items == 1
        assert run.succeeded_items == 1
        assert run.executed_by_username == "admin"
        assert run.target_database == "Sub2API Admin API (https://sub2api.example.com)"
        assert run.items[0]["status"] == "succeeded"
        assert run.items[0]["priority"] == 5
        assert run.items[0]["matched_accounts"] == 1
        assert run.items[0]["updated_accounts"] == 1
        assert run.items[0]["sql_log_id"] is None
        assert "获得 Priority 5" in run.items[0]["change_reason"]
        assert run.items[0]["admin_api_method"] == "POST"
        assert run.items[0]["admin_api_path"] == "/api/v1/admin/accounts/bulk-update"
        assert run.items[0]["admin_api_payload"] == {"account_ids": [101], "priority": 5}
        assert run.items[0]["admin_api_response"]["success_ids"] == [101]
        assert run.items[0]["matched_account_items"][0]["id"] == 101
        assert run.items[0]["matched_account_items"][0]["priority_before"] is None
        assert calls == [([101], {"priority": 5})]
        assert db.scalars(select(Sub2APISQLLog)).all() == []
    finally:
        db.close()


def test_priority_sync_resolves_account_ids_from_sub2api_database(monkeypatch) -> None:
    db = make_session()
    calls: list[tuple[list[int], dict[str, object]]] = []

    class FakeAdminClient:
        def __init__(self, settings):  # noqa: ANN001
            self.settings = settings

        async def list_accounts(self):
            raise AssertionError("database lookup should avoid listing accounts")

        async def bulk_update_accounts(self, account_ids, updates):  # noqa: ANN001
            ids = list(account_ids)
            calls.append((ids, dict(updates)))
            return {"success": len(ids), "failed": 0, "success_ids": ids, "failed_ids": []}

    def fake_load_target_accounts(database, normalized_base_url):  # noqa: ANN001
        assert database.is_configured is True
        assert normalized_base_url == "https://relay.example.com"
        return [
            {
                "id": 201,
                "name": "database matched",
                "platform": "openai",
                "type": "chat",
                "status": "active",
                "schedulable": True,
                "priority_before": 25,
                "matched_base_url": "https://relay.example.com",
                "account_base_urls": ["https://relay.example.com"],
                "lookup_source": "database",
            }
        ]

    monkeypatch.setattr(
        "app.services.priority_sync.Sub2APIAdminClient",
        FakeAdminClient,
    )
    monkeypatch.setattr(
        "app.services.priority_sync.load_priority_sync_target_accounts",
        fake_load_target_accounts,
    )
    try:
        platform = RelayPlatform(
            name="Database Sync Target",
            base_url="https://relay.example.com/",
            provider_type="fake",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        account = PlatformAccountMonitor(
            platform_id=platform.id,
            name="Main",
            external_account_id="main",
            enabled=True,
        )
        account.key_summaries = (
            {"id": "101", "name": "main-key", "group_id": "7", "group_name": "codex"},
        )
        db.add_all(
            [
                account,
                PlatformGroupMonitor(
                    platform_id=platform.id,
                    name="codex",
                    external_group_id="7",
                    enabled=True,
                    rate_multiplier=0.08,
                ),
            ]
        )
        db.commit()

        run = asyncio.run(
            sync_sub2api_account_priorities(
                db,
                database=Sub2APIDatabaseSettings(
                    host="sub2api-postgres",
                    user="newapi",
                    password="secret",
                    dbname="sub2api",
                ),
                sub2api_settings=Sub2APISettings(
                    admin_base_url="https://sub2api.example.com",
                    admin_api_key="admin-key",
                ),
            )
        )

        assert run.status == "succeeded"
        assert run.items[0]["account_lookup_source"] == "database"
        assert run.items[0]["matched_accounts"] == 1
        assert run.items[0]["updated_accounts"] == 1
        assert run.items[0]["admin_api_payload"] == {"account_ids": [201], "priority": 5}
        assert run.items[0]["matched_account_items"][0]["priority_before"] == 25
        assert calls == [([201], {"priority": 5})]
    finally:
        db.close()


def test_priority_sync_fails_when_admin_api_is_unconfigured() -> None:
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Sync Target",
            base_url="https://relay.example.com/",
            provider_type="fake",
            rate_cron="*/10 * * * *",
            balance_cron="*/10 * * * *",
            status=PlatformStatus.unknown,
        )
        db.add(platform)
        db.flush()
        account = PlatformAccountMonitor(
            platform_id=platform.id,
            name="Main",
            external_account_id="main",
            enabled=True,
        )
        account.key_summaries = (
            {"id": "101", "name": "main-key", "group_id": "7", "group_name": "codex"},
        )
        db.add_all(
            [
                account,
                PlatformGroupMonitor(
                    platform_id=platform.id,
                    name="codex",
                    external_group_id="7",
                    enabled=True,
                    rate_multiplier=0.08,
                ),
            ]
        )
        db.commit()

        run = asyncio.run(
            sync_sub2api_account_priorities(
                db,
                database=Sub2APIDatabaseSettings(user="", password="", dbname="sub2api"),
            )
        )

        expected = "Sub2API Admin API is not configured"
        assert run.status == "failed"
        assert run.error_message == expected
        assert run.items[0]["status"] == "failed"
        assert run.items[0]["error_message"] == expected
        assert db.scalars(select(Sub2APISQLLog)).all() == []
    finally:
        db.close()


def test_auto_schedulable_suspends_matching_schedulable_accounts(monkeypatch) -> None:
    db = make_session()
    calls: list[tuple[list[int], bool]] = []

    class FakeAdminClient:
        def __init__(self, settings):  # noqa: ANN001
            self.settings = settings

        async def list_accounts(self):
            return [
                {
                    "id": 101,
                    "name": "matched",
                    "schedulable": True,
                    "credentials": {"base_url": "https://relay.example.com/"},
                },
                {
                    "id": 102,
                    "name": "manual-off",
                    "schedulable": False,
                    "credentials": {"base_url": "https://relay.example.com"},
                },
                {
                    "id": 103,
                    "name": "other",
                    "schedulable": True,
                    "credentials": {"base_url": "https://other.example.com"},
                },
            ]

        async def bulk_set_schedulable(self, account_ids, schedulable):  # noqa: ANN001
            ids = list(account_ids)
            calls.append((ids, schedulable))
            return {"success": len(ids), "failed": 0, "success_ids": ids, "failed_ids": []}

    monkeypatch.setattr(
        "app.services.sub2api_schedulable.Sub2APIAdminClient",
        FakeAdminClient,
    )
    settings = Sub2APISettings(
        admin_base_url="https://sub2api.example.com",
        admin_api_key="admin-key",
        auto_schedulable_enabled=True,
        auto_schedulable_failure_threshold=2,
    )

    try:
        asyncio.run(
            record_sub2api_monitor_failure(
                db,
                platform_id=7,
                platform_name="Relay",
                base_url="https://relay.example.com/",
                error_message="first failure",
                settings=settings,
            )
        )
        assert calls == []

        asyncio.run(
            record_sub2api_monitor_failure(
                db,
                platform_id=7,
                platform_name="Relay",
                base_url="https://relay.example.com/",
                error_message="second failure",
                settings=settings,
            )
        )

        assert calls == [([101], False)]
        state = db.scalar(select(Sub2APIMonitorFailureState))
        assert state is not None
        assert state.consecutive_failures == 2
        assert state.paused is True
        suspended = db.scalars(select(Sub2APIMonitorSuspendedAccount)).all()
        assert len(suspended) == 1
        assert suspended[0].account_id == 101
        assert suspended[0].account_name == "matched"
        assert suspended[0].restored is False
    finally:
        db.close()


def test_auto_schedulable_uses_configured_failure_threshold(monkeypatch) -> None:
    db = make_session()
    calls: list[tuple[list[int], bool]] = []

    class FakeAdminClient:
        def __init__(self, settings):  # noqa: ANN001
            self.settings = settings

        async def list_accounts(self):
            return [
                {
                    "id": "201",
                    "name": "matched string schedulable",
                    "schedulable": "true",
                    "credentials": {"base_url": "https://relay.example.com/"},
                }
            ]

        async def bulk_set_schedulable(self, account_ids, schedulable):  # noqa: ANN001
            ids = list(account_ids)
            calls.append((ids, schedulable))
            return {"success": len(ids), "failed": 0, "success_ids": ids, "failed_ids": []}

    monkeypatch.setattr(
        "app.services.sub2api_schedulable.Sub2APIAdminClient",
        FakeAdminClient,
    )
    settings = Sub2APISettings(
        admin_base_url="https://sub2api.example.com",
        admin_api_key="admin-key",
        auto_schedulable_enabled=True,
        auto_schedulable_failure_threshold=4,
    )

    try:
        for index in range(1, 4):
            asyncio.run(
                record_sub2api_monitor_result(
                    db,
                    platform_id=9,
                    platform_name="Relay",
                    base_url="https://relay.example.com/",
                    error_message=f"failure {index}",
                    settings=settings,
                )
            )
            assert calls == []

        asyncio.run(
            record_sub2api_monitor_result(
                db,
                platform_id=9,
                platform_name="Relay",
                base_url="https://relay.example.com/",
                error_message="failure 4",
                settings=settings,
            )
        )

        assert calls == [([201], False)]
        state = db.scalar(
            select(Sub2APIMonitorFailureState).where(
                Sub2APIMonitorFailureState.platform_id == 9,
            )
        )
        assert state is not None
        assert state.consecutive_failures == 4
        assert state.paused is True
        suspended = db.scalars(select(Sub2APIMonitorSuspendedAccount)).all()
        assert len(suspended) == 1
        assert suspended[0].account_id == 201
        assert suspended[0].account_name == "matched string schedulable"
    finally:
        db.close()


def test_auto_schedulable_success_restores_monitor_suspended_accounts(monkeypatch) -> None:
    db = make_session()
    calls: list[tuple[list[int], bool]] = []

    class FakeAdminClient:
        def __init__(self, settings):  # noqa: ANN001
            self.settings = settings

        async def bulk_set_schedulable(self, account_ids, schedulable):  # noqa: ANN001
            ids = list(account_ids)
            calls.append((ids, schedulable))
            return {"success": len(ids), "failed": 0, "success_ids": ids, "failed_ids": []}

    monkeypatch.setattr(
        "app.services.sub2api_schedulable.Sub2APIAdminClient",
        FakeAdminClient,
    )
    settings = Sub2APISettings(
        admin_base_url="https://sub2api.example.com/api/v1",
        admin_api_key="admin-key",
        auto_schedulable_enabled=True,
        auto_schedulable_failure_threshold=2,
    )
    try:
        db.add(
            Sub2APIMonitorFailureState(
                platform_id=7,
                platform_name="Relay",
                base_url="https://relay.example.com",
                consecutive_failures=3,
                last_error="failed",
                paused=True,
            )
        )
        db.add(
            Sub2APIMonitorSuspendedAccount(
                platform_id=7,
                platform_name="Relay",
                base_url="https://relay.example.com",
                account_id=101,
                account_name="matched",
                restored=False,
            )
        )
        db.add(
            Sub2APIMonitorSuspendedAccount(
                platform_id=8,
                platform_name="Other",
                base_url="https://other.example.com",
                account_id=201,
                account_name="other",
                restored=False,
            )
        )
        db.commit()

        asyncio.run(
            record_sub2api_monitor_success(
                db,
                platform_id=7,
                platform_name="Relay",
                base_url="https://relay.example.com/",
                settings=settings,
            )
        )

        assert calls == [([101], True)]
        state = db.scalar(
            select(Sub2APIMonitorFailureState).where(
                Sub2APIMonitorFailureState.platform_id == 7,
            )
        )
        assert state is not None
        assert state.consecutive_failures == 0
        assert state.paused is False
        restored = db.scalar(
            select(Sub2APIMonitorSuspendedAccount).where(
                Sub2APIMonitorSuspendedAccount.account_id == 101,
            )
        )
        assert restored is not None
        assert restored.restored is True
        untouched = db.scalar(
            select(Sub2APIMonitorSuspendedAccount).where(
                Sub2APIMonitorSuspendedAccount.account_id == 201,
            )
        )
        assert untouched is not None
        assert untouched.restored is False
    finally:
        db.close()
