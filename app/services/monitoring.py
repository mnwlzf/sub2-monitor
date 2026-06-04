from croniter import croniter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.security import utcnow
from app.models.platform import PlatformStatus, RelayPlatform
from app.services.provider_strategy import provider_registry


async def run_platform_monitor(db: Session, platform_id: int) -> RelayPlatform:
    platform = await run_platform_balance_monitor(db, platform_id)
    platform = await run_platform_rate_monitor(db, platform_id)
    return platform


async def run_platform_balance_monitor(db: Session, platform_id: int) -> RelayPlatform:
    platform = db.scalar(
        select(RelayPlatform)
        .options(
            selectinload(RelayPlatform.account_monitors),
        )
        .where(RelayPlatform.id == platform_id)
    )
    if platform is None:
        raise LookupError("Platform not found")

    strategy = provider_registry.get(platform.provider_type)
    errors: list[str] = []

    for account in platform.account_monitors:
        if not account.enabled:
            continue
        try:
            result = await strategy.fetch_account_balance(platform, account)
            account.balance = result.balance
            account.quota_used = result.quota_used
            account.quota_limit = result.quota_limit
            account.last_error = result.error
            if result.error:
                errors.append(f"account {account.name}: {result.error}")
        except Exception as exc:  # noqa: BLE001
            account.last_error = str(exc)
            errors.append(f"account {account.name}: {exc}")
        account.checked_at = utcnow()
        db.add(account)

    account_balances = [
        account.balance
        for account in platform.account_monitors
        if account.enabled and account.balance is not None
    ]
    account_quota_used = [
        account.quota_used
        for account in platform.account_monitors
        if account.enabled and account.quota_used is not None
    ]
    account_quota_limits = [
        account.quota_limit
        for account in platform.account_monitors
        if account.enabled and account.quota_limit is not None
    ]
    platform.balance = sum(account_balances) if account_balances else None
    platform.quota_used = sum(account_quota_used) if account_quota_used else None
    platform.quota_limit = sum(account_quota_limits) if account_quota_limits else None

    now = utcnow()
    platform.balance_last_run_at = now
    platform.balance_next_run_at = croniter(platform.balance_cron, now).get_next(type(now))
    update_platform_status(platform, errors)
    db.add(platform)
    db.commit()
    db.refresh(platform)
    return platform


async def run_platform_rate_monitor(db: Session, platform_id: int) -> RelayPlatform:
    platform = db.scalar(
        select(RelayPlatform)
        .options(
            selectinload(RelayPlatform.group_monitors),
        )
        .where(RelayPlatform.id == platform_id)
    )
    if platform is None:
        raise LookupError("Platform not found")

    strategy = provider_registry.get(platform.provider_type)
    errors: list[str] = []

    for group in platform.group_monitors:
        if not group.enabled:
            continue
        try:
            result = await strategy.fetch_group_rate(platform, group)
            group.rate_multiplier = result.rate_multiplier
            group.rpm_limit = result.rpm_limit
            group.last_error = result.error
            if result.error:
                errors.append(f"group {group.name}: {result.error}")
        except Exception as exc:  # noqa: BLE001
            group.last_error = str(exc)
            errors.append(f"group {group.name}: {exc}")
        group.checked_at = utcnow()
        db.add(group)

    now = utcnow()
    platform.rate_last_run_at = now
    platform.rate_next_run_at = croniter(platform.rate_cron, now).get_next(type(now))
    update_platform_status(platform, errors)
    db.add(platform)
    db.commit()
    db.refresh(platform)
    return platform


def update_platform_status(platform: RelayPlatform, errors: list[str]) -> None:
    platform.checked_at = utcnow()
    platform.last_error = "\n".join(errors) if errors else None
    platform.status = PlatformStatus.degraded if errors else PlatformStatus.healthy


def get_platform_detail(db: Session, platform_id: int) -> RelayPlatform | None:
    return db.scalar(
        select(RelayPlatform)
        .options(
            selectinload(RelayPlatform.account_monitors),
            selectinload(RelayPlatform.group_monitors),
        )
        .where(RelayPlatform.id == platform_id)
    )
