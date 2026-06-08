from dataclasses import dataclass
import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Sub2APIDatabaseSettings
from app.models.sub2api import Sub2APISQLLog
from app.models.user import User

SQLParams = Mapping[str, Any] | Sequence[Any] | None


@dataclass(frozen=True)
class Sub2APIDatabaseProbe:
    ok: bool
    error: str | None = None
    current_database: str | None = None
    current_user: str | None = None
    server_version: str | None = None


def safe_database_config(database: Sub2APIDatabaseSettings) -> dict[str, Any]:
    return {
        "configured": database.is_configured,
        "host": database.host,
        "port": database.port,
        "user": database.user,
        "dbname": database.dbname,
        "sslmode": database.sslmode,
        "has_password": database.has_password,
        "dsn": database.masked_dsn(),
        "connect_timeout_seconds": database.connect_timeout_seconds,
    }


def target_database_label(database: Sub2APIDatabaseSettings) -> str:
    return database.masked_dsn() or f"{database.host}:{database.port}/{database.dbname}"


def sql_params_json(params: SQLParams) -> str | None:
    if params is None:
        return None
    return json.dumps(params, ensure_ascii=False, default=str)


def create_sql_log(
    db: Session,
    *,
    operation: str,
    database: Sub2APIDatabaseSettings,
    sql_text: str,
    sql_params: SQLParams = None,
    status: str = "pending",
    affected_rows: int | None = None,
    error_message: str | None = None,
    user: User | None = None,
) -> Sub2APISQLLog:
    log = Sub2APISQLLog(
        operation=operation,
        target_database=target_database_label(database),
        sql_text=sql_text,
        sql_params_json=sql_params_json(sql_params),
        status=status,
        affected_rows=affected_rows,
        error_message=error_message,
        executed_by_user_id=user.id if user else None,
        executed_by_username=user.username if user else None,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def update_sql_log_result(
    db: Session,
    log: Sub2APISQLLog,
    *,
    status: str,
    affected_rows: int | None = None,
    error_message: str | None = None,
) -> Sub2APISQLLog:
    log.status = status
    log.affected_rows = affected_rows
    log.error_message = error_message
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def execute_recorded_sub2api_write(
    db: Session,
    *,
    database: Sub2APIDatabaseSettings,
    operation: str,
    sql_text: str,
    sql_params: SQLParams = None,
    user: User | None = None,
) -> Sub2APISQLLog:
    log = create_sql_log(
        db,
        operation=operation,
        database=database,
        sql_text=sql_text,
        sql_params=sql_params,
        user=user,
    )

    if not database.is_configured:
        return update_sql_log_result(
            db,
            log,
            status="failed",
            error_message="Sub2API database is not configured",
        )

    try:
        import psycopg
    except ImportError:
        return update_sql_log_result(
            db,
            log,
            status="failed",
            error_message="psycopg is not installed",
        )

    try:
        with psycopg.connect(
            database.postgresql_dsn(),
            connect_timeout=database.connect_timeout_seconds,
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql_text, sql_params)
                affected_rows = cursor.rowcount if cursor.rowcount >= 0 else None
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        return update_sql_log_result(
            db,
            log,
            status="failed",
            error_message=str(exc),
        )

    return update_sql_log_result(
        db,
        log,
        status="succeeded",
        affected_rows=affected_rows,
    )


def probe_sub2api_database(database: Sub2APIDatabaseSettings) -> Sub2APIDatabaseProbe:
    if not database.is_configured:
        return Sub2APIDatabaseProbe(ok=False, error="Sub2API database is not configured")

    try:
        import psycopg
    except ImportError:
        return Sub2APIDatabaseProbe(ok=False, error="psycopg is not installed")

    try:
        with psycopg.connect(
            database.postgresql_dsn(),
            connect_timeout=database.connect_timeout_seconds,
        ) as conn:
            conn.read_only = True
            with conn.cursor() as cursor:
                cursor.execute("select current_database(), current_user, version()")
                current_database, current_user, server_version = cursor.fetchone()
    except Exception as exc:  # noqa: BLE001
        return Sub2APIDatabaseProbe(ok=False, error=str(exc))

    return Sub2APIDatabaseProbe(
        ok=True,
        current_database=current_database,
        current_user=current_user,
        server_version=server_version,
    )
