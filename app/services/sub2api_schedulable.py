import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Sub2APISettings
from app.core.security import utcnow
from app.models.sub2api import Sub2APIMonitorFailureState, Sub2APIMonitorSuspendedAccount
from app.services.sub2api_admin import Sub2APIAdminClient, Sub2APIAdminSettings

logger = logging.getLogger(__name__)


def normalize_base_url(value: str | None) -> str:
    return (value or "").strip().rstrip("/")


def account_id(account: dict[str, Any]) -> int | None:
    raw_id = account.get("id")
    if isinstance(raw_id, int):
        return raw_id
    if isinstance(raw_id, str) and raw_id.isdigit():
        return int(raw_id)
    return None


def account_name(account: dict[str, Any]) -> str | None:
    name = account.get("name")
    return str(name) if name is not None else None


def account_base_urls(account: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    credentials = account.get("credentials")
    if isinstance(credentials, dict):
        base_url = credentials.get("base_url")
        normalized = normalize_base_url(str(base_url)) if base_url is not None else ""
        if normalized:
            urls.add(normalized)

    extra = account.get("extra")
    if isinstance(extra, dict) and str(extra.get("custom_base_url_enabled")).lower() == "true":
        custom_base_url = extra.get("custom_base_url")
        normalized = normalize_base_url(str(custom_base_url)) if custom_base_url is not None else ""
        if normalized:
            urls.add(normalized)
    return urls


def matches_platform_base_url(account: dict[str, Any], normalized_base_url: str) -> bool:
    return normalized_base_url in account_base_urls(account)


def is_schedulable_enabled(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, int) and value == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes", "on"}:
        return True
    return False


def get_failure_state(
    db: Session,
    *,
    platform_id: int,
    platform_name: str | None,
    base_url: str,
) -> Sub2APIMonitorFailureState:
    state = db.scalar(
        select(Sub2APIMonitorFailureState).where(
            Sub2APIMonitorFailureState.platform_id == platform_id,
        )
    )
    if state is None:
        state = Sub2APIMonitorFailureState(
            platform_id=platform_id,
            platform_name=platform_name,
            base_url=base_url,
            consecutive_failures=0,
            paused=False,
        )
    else:
        state.platform_name = platform_name
        state.base_url = base_url
    return state


async def record_sub2api_monitor_success(
    db: Session,
    *,
    platform_id: int,
    platform_name: str | None,
    base_url: str,
    settings: Sub2APISettings,
) -> None:
    if not settings.auto_schedulable_enabled:
        return

    state = get_failure_state(
        db,
        platform_id=platform_id,
        platform_name=platform_name,
        base_url=base_url,
    )
    state.consecutive_failures = 0
    state.last_error = None
    db.add(state)
    db.commit()

    await restore_monitor_suspended_accounts(
        db,
        platform_id=platform_id,
        platform_name=platform_name,
        base_url=base_url,
        settings=settings,
    )


async def record_sub2api_monitor_failure(
    db: Session,
    *,
    platform_id: int,
    platform_name: str | None,
    base_url: str,
    error_message: str,
    settings: Sub2APISettings,
) -> None:
    if not settings.auto_schedulable_enabled:
        return

    state = get_failure_state(
        db,
        platform_id=platform_id,
        platform_name=platform_name,
        base_url=base_url,
    )
    state.consecutive_failures += 1
    state.last_error = error_message
    db.add(state)
    db.commit()

    if state.consecutive_failures < settings.auto_schedulable_failure_threshold:
        return
    if state.paused:
        return

    await suspend_matching_sub2api_accounts(
        db,
        platform_id=platform_id,
        platform_name=platform_name,
        base_url=base_url,
        error_message=error_message,
        settings=settings,
    )


async def record_sub2api_monitor_result(
    db: Session,
    *,
    platform_id: int,
    platform_name: str | None,
    base_url: str,
    error_message: str | None,
    settings: Sub2APISettings,
) -> None:
    if error_message:
        await record_sub2api_monitor_failure(
            db,
            platform_id=platform_id,
            platform_name=platform_name,
            base_url=base_url,
            error_message=error_message,
            settings=settings,
        )
        return

    await record_sub2api_monitor_success(
        db,
        platform_id=platform_id,
        platform_name=platform_name,
        base_url=base_url,
        settings=settings,
    )


async def suspend_matching_sub2api_accounts(
    db: Session,
    *,
    platform_id: int,
    platform_name: str | None,
    base_url: str,
    error_message: str,
    settings: Sub2APISettings,
) -> None:
    admin_settings = Sub2APIAdminSettings(
        base_url=settings.admin_base_url,
        api_key=settings.admin_api_key,
    )
    if not admin_settings.is_configured:
        logger.warning("sub2api auto schedulable skipped: admin API is not configured")
        return

    normalized_base_url = normalize_base_url(base_url)
    client = Sub2APIAdminClient(admin_settings)
    accounts = await client.list_accounts()
    targets = [
        account
        for account in accounts
        if matches_platform_base_url(account, normalized_base_url)
        and is_schedulable_enabled(account.get("schedulable"))
        and account_id(account) is not None
    ]
    ids = [account_id(account) for account in targets]
    target_ids = [item for item in ids if item is not None]
    if not target_ids:
        return

    result = await client.bulk_set_schedulable(target_ids, False)
    success_ids = bulk_success_ids(result, target_ids)
    now = utcnow()
    for account in targets:
        external_id = account_id(account)
        if external_id is None or external_id not in success_ids:
            continue
        existing = db.scalar(
            select(Sub2APIMonitorSuspendedAccount).where(
                Sub2APIMonitorSuspendedAccount.platform_id == platform_id,
                Sub2APIMonitorSuspendedAccount.account_id == external_id,
                Sub2APIMonitorSuspendedAccount.restored.is_(False),
            )
        )
        if existing is not None:
            continue
        db.add(
            Sub2APIMonitorSuspendedAccount(
                platform_id=platform_id,
                platform_name=platform_name,
                base_url=normalized_base_url,
                account_id=external_id,
                account_name=account_name(account),
                pause_error=error_message,
                paused_at=now,
            )
        )

    state = get_failure_state(
        db,
        platform_id=platform_id,
        platform_name=platform_name,
        base_url=normalized_base_url,
    )
    state.paused = True
    db.add(state)
    db.commit()


async def restore_monitor_suspended_accounts(
    db: Session,
    *,
    platform_id: int,
    platform_name: str | None,
    base_url: str,
    settings: Sub2APISettings,
) -> None:
    admin_settings = Sub2APIAdminSettings(
        base_url=settings.admin_base_url,
        api_key=settings.admin_api_key,
    )
    if not admin_settings.is_configured:
        return

    rows = list(
        db.scalars(
            select(Sub2APIMonitorSuspendedAccount).where(
                Sub2APIMonitorSuspendedAccount.platform_id == platform_id,
                Sub2APIMonitorSuspendedAccount.restored.is_(False),
            )
        ).all()
    )
    if not rows:
        return

    client = Sub2APIAdminClient(admin_settings)
    ids = [row.account_id for row in rows]
    result = await client.bulk_set_schedulable(ids, True)
    success_ids = bulk_success_ids(result, ids)
    now = utcnow()
    for row in rows:
        if row.account_id not in success_ids:
            row.restore_error = "Sub2API bulk-update did not report this account as succeeded"
            db.add(row)
            continue
        row.restored = True
        row.restored_at = now
        row.restore_error = None
        db.add(row)

    state = get_failure_state(
        db,
        platform_id=platform_id,
        platform_name=platform_name,
        base_url=normalize_base_url(base_url),
    )
    if all(row.restored for row in rows):
        state.paused = False
    db.add(state)
    db.commit()


def bulk_success_ids(payload: dict[str, Any], fallback_ids: list[int]) -> set[int]:
    raw_ids = payload.get("success_ids")
    if isinstance(raw_ids, list):
        ids: set[int] = set()
        for raw_id in raw_ids:
            if isinstance(raw_id, int):
                ids.add(raw_id)
            elif isinstance(raw_id, str) and raw_id.isdigit():
                ids.add(int(raw_id))
        return ids
    if int(payload.get("failed") or 0) == 0:
        return set(fallback_ids)
    return set()
