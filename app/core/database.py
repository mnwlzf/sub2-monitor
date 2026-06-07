from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

if settings.database_url.startswith("sqlite:///"):
    sqlite_path = settings.database_url.removeprefix("sqlite:///")
    if sqlite_path.startswith("./"):
        sqlite_path = sqlite_path[2:]
    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema() -> None:
    Base.metadata.create_all(bind=engine)
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "relay_platforms" not in table_names:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("relay_platforms")}
    column_sql = {
        "site_strategy": "ALTER TABLE relay_platforms ADD COLUMN site_strategy VARCHAR(64) NOT NULL DEFAULT 'generic'",
        "auth_header_name": "ALTER TABLE relay_platforms ADD COLUMN auth_header_name VARCHAR(64) NOT NULL DEFAULT 'Authorization'",
        "auth_header_prefix": "ALTER TABLE relay_platforms ADD COLUMN auth_header_prefix VARCHAR(32) NOT NULL DEFAULT 'Bearer'",
        "api_key_encrypted": "ALTER TABLE relay_platforms ADD COLUMN api_key_encrypted TEXT",
        "balance_cron": "ALTER TABLE relay_platforms ADD COLUMN balance_cron VARCHAR(64) NOT NULL DEFAULT '*/10 * * * *'",
        "rate_cron": "ALTER TABLE relay_platforms ADD COLUMN rate_cron VARCHAR(64) NOT NULL DEFAULT '0 * * * *'",
        "recharge_amount": "ALTER TABLE relay_platforms ADD COLUMN recharge_amount FLOAT NOT NULL DEFAULT 1.0",
        "received_amount": "ALTER TABLE relay_platforms ADD COLUMN received_amount FLOAT NOT NULL DEFAULT 1.0",
        "balance_last_run_at": "ALTER TABLE relay_platforms ADD COLUMN balance_last_run_at DATETIME",
        "balance_next_run_at": "ALTER TABLE relay_platforms ADD COLUMN balance_next_run_at DATETIME",
        "rate_last_run_at": "ALTER TABLE relay_platforms ADD COLUMN rate_last_run_at DATETIME",
        "rate_next_run_at": "ALTER TABLE relay_platforms ADD COLUMN rate_next_run_at DATETIME",
    }
    with engine.begin() as conn:
        for column, statement in column_sql.items():
            if column not in existing_columns:
                conn.execute(text(statement))

    if "platform_account_monitors" in table_names:
        account_columns = {
            column["name"] for column in inspector.get_columns("platform_account_monitors")
        }
        account_column_sql = {
            "username": "ALTER TABLE platform_account_monitors ADD COLUMN username VARCHAR(160)",
            "password_encrypted": "ALTER TABLE platform_account_monitors ADD COLUMN password_encrypted TEXT",
            "key_summaries_json": "ALTER TABLE platform_account_monitors ADD COLUMN key_summaries_json TEXT",
        }
        with engine.begin() as conn:
            for column, statement in account_column_sql.items():
                if column not in account_columns:
                    conn.execute(text(statement))

    if "platform_discovered_group_rates" in table_names:
        discovered_columns = {
            column["name"] for column in inspector.get_columns("platform_discovered_group_rates")
        }
        discovered_column_sql = {
            "description": "ALTER TABLE platform_discovered_group_rates ADD COLUMN description TEXT",
        }
        with engine.begin() as conn:
            for column, statement in discovered_column_sql.items():
                if column not in discovered_columns:
                    conn.execute(text(statement))

    if "discovered_group_rate_snapshots" in table_names:
        discovered_snapshot_columns = {
            column["name"] for column in inspector.get_columns("discovered_group_rate_snapshots")
        }
        discovered_snapshot_column_sql = {
            "description": "ALTER TABLE discovered_group_rate_snapshots ADD COLUMN description TEXT",
        }
        with engine.begin() as conn:
            for column, statement in discovered_snapshot_column_sql.items():
                if column not in discovered_snapshot_columns:
                    conn.execute(text(statement))

    if "notification_settings" in table_names:
        notification_columns = {
            column["name"] for column in inspector.get_columns("notification_settings")
        }
        notification_column_sql = {
            "smtp_use_ssl": "ALTER TABLE notification_settings ADD COLUMN smtp_use_ssl BOOLEAN NOT NULL DEFAULT 0",
        }
        with engine.begin() as conn:
            for column, statement in notification_column_sql.items():
                if column not in notification_columns:
                    conn.execute(text(statement))

        if "notification_recipients" in table_names and "recipient_email" in notification_columns:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO notification_recipients (name, email, enabled, created_at, updated_at)
                        SELECT '默认收件人', recipient_email, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        FROM notification_settings
                        WHERE recipient_email IS NOT NULL
                          AND recipient_email != ''
                          AND NOT EXISTS (
                              SELECT 1
                              FROM notification_recipients
                              WHERE notification_recipients.email = notification_settings.recipient_email
                          )
                        """
                    )
                )
