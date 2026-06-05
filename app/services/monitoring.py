from datetime import datetime

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.security import utcnow
from app.models.monitor import PlatformDiscoveredGroupRate, PlatformGroupMonitor
from app.models.platform import PlatformStatus, RelayPlatform
from app.models.snapshot import AccountBalanceSnapshot, GroupRateSnapshot
from app.services.provider_strategy import (
    DiscoveredGroupRateResult,
    provider_registry,
)


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
        checked_at = utcnow()
        account.checked_at = checked_at
        db.add(account)
        db.add(
            AccountBalanceSnapshot(
                platform_id=platform.id,
                account_monitor_id=account.id,
                balance=account.balance,
                quota_used=account.quota_used,
                quota_limit=account.quota_limit,
                error_message=account.last_error,
                created_at=checked_at,
            )
        )

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
            selectinload(RelayPlatform.discovered_group_rates),
        )
        .where(RelayPlatform.id == platform_id)
    )
    if platform is None:
        raise LookupError("Platform not found")

    strategy = provider_registry.get(platform.provider_type)
    errors: list[str] = []

    discovered_catalog: list[DiscoveredGroupRateResult] | None
    try:
        discovered_catalog = await strategy.fetch_group_catalog(platform)
    except Exception as exc:  # noqa: BLE001
        discovered_catalog = None
        errors.append(f"group catalog fetch failed: {exc}")

    if discovered_catalog is not None:
        for discovered_group in list(platform.discovered_group_rates):
            db.delete(discovered_group)
        configured_groups = {
            group.external_group_id: group
            for group in platform.group_monitors
        }
        for item in discovered_catalog:
            checked_at = utcnow()
            configured_group = configured_groups.get(item.external_group_id)
            record_discovered_group_rate(
                db=db,
                platform=platform,
                external_group_id=item.external_group_id,
                name=item.name,
                description=item.description,
                rate_multiplier=item.rate_multiplier,
                rpm_limit=item.rpm_limit,
                error=item.error,
                checked_at=checked_at,
            )
            if configured_group is not None:
                record_configured_group_rate(
                    db=db,
                    platform=platform,
                    group=configured_group,
                    rate_multiplier=item.rate_multiplier,
                    rpm_limit=item.rpm_limit,
                    error=item.error,
                    checked_at=checked_at,
                )
            if item.error:
                errors.append(f"group {item.name}: {item.error}")

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
            selectinload(RelayPlatform.discovered_group_rates),
        )
        .where(RelayPlatform.id == platform_id)
    )


def record_discovered_group_rate(
    db: Session,
    platform: RelayPlatform,
    external_group_id: str,
    name: str,
    description: str | None,
    rate_multiplier: float | None,
    rpm_limit: int | None,
    error: str | None,
    checked_at: datetime | None = None,
) -> None:
    if checked_at is None:
        checked_at = utcnow()
    db.add(
        PlatformDiscoveredGroupRate(
            platform_id=platform.id,
            external_group_id=external_group_id,
            name=name,
            description=description,
            rate_multiplier=rate_multiplier,
            rpm_limit=rpm_limit,
            last_error=error,
            checked_at=checked_at,
        )
    )


def record_configured_group_rate(
    db: Session,
    platform: RelayPlatform,
    group: PlatformGroupMonitor,
    rate_multiplier: float | None,
    rpm_limit: int | None,
    error: str | None,
    checked_at: datetime | None = None,
) -> None:
    if checked_at is None:
        checked_at = utcnow()
    group.rate_multiplier = rate_multiplier
    group.rpm_limit = rpm_limit
    group.last_error = error
    group.checked_at = checked_at
    db.add(group)
    db.add(
        GroupRateSnapshot(
            platform_id=platform.id,
            group_monitor_id=group.id,
            rate_multiplier=rate_multiplier,
            rpm_limit=rpm_limit,
            error_message=error,
            created_at=checked_at,
        )
    )
