from dataclasses import dataclass
from typing import Any

from app.core.config import Sub2APIDatabaseSettings


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
