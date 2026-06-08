import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models.all  # noqa: F401
from app.api.sub2api import get_sql_log, list_sql_logs
from app.core.config import Sub2APIDatabaseSettings
from app.core.database import Base
from app.models.user import User
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
