import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models.all  # noqa: F401
from app.api.sub2api import get_sql_log, list_sql_logs
from app.core.config import Sub2APIDatabaseSettings
from app.core.database import Base
from app.core.security import encrypt_secret
from app.models.monitor import PlatformAccountMonitor, PlatformGroupMonitor
from app.models.platform import PlatformStatus, RelayPlatform
from app.models.sub2api import Sub2APISQLLog
from app.models.user import User
from app.services.priority_sync import (
    PRIORITY_SYNC_PRIORITY_STEP,
    PRIORITY_SYNC_SQL,
    build_priority_sync_plan,
    sync_sub2api_account_priorities,
)
from app.services.sub2api_database import create_sql_log, execute_recorded_sub2api_write


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


def test_priority_sync_sql_targets_sub2api_accounts_url_fields() -> None:
    assert PRIORITY_SYNC_PRIORITY_STEP == 5
    assert "UPDATE accounts" in PRIORITY_SYNC_SQL
    assert "SET priority = %(priority)s" in PRIORITY_SYNC_SQL
    assert "credentials->>'api_key'" not in PRIORITY_SYNC_SQL
    assert "credentials->>'base_url'" in PRIORITY_SYNC_SQL
    assert "extra->>'custom_base_url'" in PRIORITY_SYNC_SQL
    assert "extra->>'custom_base_url_enabled'" in PRIORITY_SYNC_SQL


def test_priority_sync_logs_failed_sql_when_target_database_is_unconfigured() -> None:
    db = make_session()
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

        run = sync_sub2api_account_priorities(
            db,
            database=Sub2APIDatabaseSettings(user="", password="", dbname="sub2api"),
            user=user,
        )

        assert run.status == "failed"
        assert run.total_items == 1
        assert run.failed_items == 1
        assert run.executed_by_username == "admin"
        assert run.items[0]["status"] == "failed"
        assert run.items[0]["priority"] == 5
        assert run.items[0]["error_message"] == "Sub2API database is not configured"

        logs = db.scalars(select(Sub2APISQLLog)).all()
        assert len(logs) == 1
        assert logs[0].operation == "sync_account_priority"
        assert logs[0].status == "failed"
        assert logs[0].executed_by_username == "admin"
        assert logs[0].sql_params_json is not None
        log_params = json.loads(logs[0].sql_params_json)
        assert log_params["base_url"] == "https://relay.example.com"
        assert "api_key" not in log_params
    finally:
        db.close()


def test_priority_sync_rejects_non_sub2api_target_database() -> None:
    db = make_session()
    try:
        platform = RelayPlatform(
            name="Wrong DB Sync Target",
            base_url="https://relay.example.com/",
            provider_type="fake",
            api_key_encrypted=encrypt_secret("sk-wrong-db"),
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

        run = sync_sub2api_account_priorities(
            db,
            database=Sub2APIDatabaseSettings(
                host="sub2api-postgres",
                user="newapi",
                password="secret",
                dbname="newapi",
            ),
        )

        expected = "Sub2API account priority sync must target database 'sub2api', got 'newapi'"
        assert run.status == "failed"
        assert run.error_message == expected
        assert run.items[0]["status"] == "failed"
        assert run.items[0]["error_message"] == expected
    finally:
        db.close()
