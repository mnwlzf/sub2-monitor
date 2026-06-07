import asyncio
import json
import logging
from datetime import datetime
from time import monotonic

from croniter import croniter
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.security import utcnow
from app.models.monitor import (
    PlatformAccountMonitor,
    PlatformDiscoveredChannelRate,
    PlatformDiscoveredGroupRate,
    PlatformGroupMonitor,
)
from app.models.platform import PlatformStatus, RelayPlatform
from app.models.snapshot import (
    AccountBalanceSnapshot,
    DiscoveredChannelRateSnapshot,
    DiscoveredGroupRateSnapshot,
    GroupRateSnapshot,
)
from app.services.notification import GroupRateChange, notify_group_rate_changes, notify_low_balance
from app.services.provider_strategy import (
    DiscoveredChannelRateResult,
    DiscoveredGroupRateResult,
    KeyGroupMonitorResult,
    provider_registry,
)

logger = logging.getLogger(__name__)


async def run_platform_monitor(db: Session, platform_id: int) -> RelayPlatform:
    platform = await run_platform_balance_monitor(db, platform_id)
    platform = await run_platform_rate_monitor(db, platform_id)
    return platform


async def run_platform_balance_monitor(db: Session, platform_id: int) -> RelayPlatform:
    platform = db.scalar(
        select(RelayPlatform)
        .options(
            selectinload(RelayPlatform.account_monitors),
            selectinload(RelayPlatform.group_monitors),
        )
        .where(RelayPlatform.id == platform_id)
    )
    if platform is None:
        raise LookupError("Platform not found")

    strategy = provider_registry.get(platform.provider_type)
    errors: list[str] = []
    started_at = monotonic()
    logger.info(
        "balance monitor start platform_id=%s name=%s provider=%s site_strategy=%s accounts=%s groups=%s",
        platform.id,
        platform.name,
        platform.provider_type,
        platform.site_strategy,
        len(platform.account_monitors),
        len(platform.group_monitors),
    )

    previous_yunjin_login_site_url: str | None = None
    for account in platform.account_monitors:
        if not account.enabled:
            continue
        yunjin_login_site_url = yunjin_account_login_site_url(strategy, platform, account)
        if (
            previous_yunjin_login_site_url is not None
            and yunjin_login_site_url is not None
            and yunjin_login_site_url == previous_yunjin_login_site_url
        ):
            await asyncio.sleep(2.0)
        if yunjin_login_site_url is not None:
            previous_yunjin_login_site_url = yunjin_login_site_url
        logger.debug(
            "balance monitor account start platform_id=%s account_id=%s account_name=%s external_account_id=%s",
            platform.id,
            account.id,
            account.name,
            account.external_account_id,
        )
        try:
            result = await strategy.fetch_account_balance(platform, account)
            account.balance = result.balance
            account.quota_used = result.quota_used
            account.quota_limit = result.quota_limit
            account.key_summaries = result.key_summaries
            account.last_error = result.error
            if result.error:
                errors.append(f"account {account.name}: {result.error}")
                logger.warning(
                    "balance monitor account failed platform_id=%s account_id=%s account_name=%s error=%s",
                    platform.id,
                    account.id,
                    account.name,
                    result.error,
                )
            else:
                logger.debug(
                    "balance monitor account done platform_id=%s account_id=%s balance=%s quota_used=%s quota_limit=%s keys=%s",
                    platform.id,
                    account.id,
                    account.balance,
                    account.quota_used,
                    account.quota_limit,
                    len(account.key_summaries),
                )
        except Exception as exc:  # noqa: BLE001
            account.last_error = str(exc)
            errors.append(f"account {account.name}: {exc}")
            logger.exception(
                "balance monitor account exception platform_id=%s account_id=%s account_name=%s",
                platform.id,
                account.id,
                account.name,
            )
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

    sync_key_group_monitors(db, platform)

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
    notify_low_balance(db, platform)
    db.add(platform)
    db.commit()
    db.refresh(platform)
    logger.info(
        "balance monitor done platform_id=%s name=%s status=%s errors=%s elapsed_ms=%s",
        platform.id,
        platform.name,
        platform.status,
        len(errors),
        int((monotonic() - started_at) * 1000),
    )
    return platform


def yunjin_account_login_site_url(
    strategy,
    platform: RelayPlatform,
    account: PlatformAccountMonitor,
) -> str | None:
    if platform.provider_type != "newapi" or platform.site_strategy != "yunjin":
        return None
    if not account.username or not account.password_encrypted:
        return None
    site_url = getattr(strategy, "site_url", None)
    if not callable(site_url):
        return platform.base_url.rstrip("/") + "/"
    return site_url(platform)


async def run_platform_rate_monitor(db: Session, platform_id: int) -> RelayPlatform:
    platform = db.scalar(
        select(RelayPlatform)
        .options(
            selectinload(RelayPlatform.account_monitors),
            selectinload(RelayPlatform.group_monitors),
        )
        .where(RelayPlatform.id == platform_id)
    )
    if platform is None:
        raise LookupError("Platform not found")

    strategy = provider_registry.get(platform.provider_type)
    errors: list[str] = []
    rate_changes: list[GroupRateChange] = []
    started_at = monotonic()
    logger.info(
        "rate monitor start platform_id=%s name=%s provider=%s site_strategy=%s groups=%s",
        platform.id,
        platform.name,
        platform.provider_type,
        platform.site_strategy,
        len(platform.group_monitors),
    )
    sync_key_group_monitors(db, platform)
    key_group_catalog_fetcher = getattr(strategy, "fetch_key_group_catalog", None)
    if callable(key_group_catalog_fetcher):
        try:
            key_group_catalog = await key_group_catalog_fetcher(platform)
        except Exception as exc:  # noqa: BLE001
            key_group_catalog = None
            errors.append(f"key group catalog fetch failed: {exc}")
            logger.exception(
                "rate monitor key group catalog failed platform_id=%s name=%s",
                platform.id,
                platform.name,
            )
    else:
        key_group_catalog = None
    if key_group_catalog is not None:
        sync_key_group_monitors(db, platform, key_group_catalog)

    discovered_channel_catalog: list[DiscoveredChannelRateResult] | None
    channel_catalog_fetcher = getattr(strategy, "fetch_channel_catalog", None)
    if callable(channel_catalog_fetcher):
        try:
            discovered_channel_catalog = await channel_catalog_fetcher(platform)
        except Exception as exc:  # noqa: BLE001
            discovered_channel_catalog = None
            errors.append(f"channel catalog fetch failed: {exc}")
            logger.exception(
                "rate monitor channel catalog failed platform_id=%s name=%s",
                platform.id,
                platform.name,
            )
    else:
        discovered_channel_catalog = None

    if discovered_channel_catalog is not None:
        db.execute(
            delete(PlatformDiscoveredChannelRate).where(
                PlatformDiscoveredChannelRate.platform_id == platform.id,
            )
        )
        db.flush()
        discovered_channels: dict[str, DiscoveredChannelRateResult] = {}
        for item in discovered_channel_catalog:
            discovered_channels[item.external_channel_id] = item
        for item in discovered_channels.values():
            checked_at = utcnow()
            record_discovered_channel_rate(
                db=db,
                platform=platform,
                external_channel_id=item.external_channel_id,
                name=item.name,
                description=item.description,
                base_url=item.base_url,
                status=item.status,
                rate_multiplier=item.rate_multiplier,
                model_rates=item.model_rates,
                error=item.error,
                checked_at=checked_at,
            )
            db.add(
                DiscoveredChannelRateSnapshot(
                    platform_id=platform.id,
                    external_channel_id=item.external_channel_id,
                    name=item.name,
                    description=item.description,
                    base_url=item.base_url,
                    status=item.status,
                    rate_multiplier=item.rate_multiplier,
                    model_rates_json=json.dumps(item.model_rates, ensure_ascii=False)
                    if item.model_rates
                    else None,
                    error_message=item.error,
                    created_at=checked_at,
                )
            )
            if item.error:
                errors.append(f"channel {item.name}: {item.error}")
                logger.warning(
                    "rate monitor channel failed platform_id=%s channel_id=%s channel_name=%s error=%s",
                    platform.id,
                    item.external_channel_id,
                    item.name,
                    item.error,
                )
            else:
                logger.debug(
                    "rate monitor channel done platform_id=%s channel_id=%s channel_name=%s rate_multiplier=%s",
                    platform.id,
                    item.external_channel_id,
                    item.name,
                    item.rate_multiplier,
                )

    discovered_catalog: list[DiscoveredGroupRateResult] | None
    try:
        discovered_catalog = await strategy.fetch_group_catalog(platform)
    except Exception as exc:  # noqa: BLE001
        discovered_catalog = None
        errors.append(f"group catalog fetch failed: {exc}")

    if discovered_catalog is not None:
        db.execute(
            delete(PlatformDiscoveredGroupRate).where(
                PlatformDiscoveredGroupRate.platform_id == platform.id,
            )
        )
        db.flush()
        configured_groups = {group.external_group_id: group for group in platform.group_monitors}
        discovered_groups: dict[str, DiscoveredGroupRateResult] = {}
        for item in discovered_catalog:
            discovered_groups[item.external_group_id] = item
        for item in discovered_groups.values():
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
            db.add(
                DiscoveredGroupRateSnapshot(
                    platform_id=platform.id,
                    external_group_id=item.external_group_id,
                    name=item.name,
                    description=item.description,
                    rate_multiplier=item.rate_multiplier,
                    rpm_limit=item.rpm_limit,
                    error_message=item.error,
                    created_at=checked_at,
                )
            )
            if configured_group is not None:
                if configured_group.enabled:
                    change = record_configured_group_rate(
                        db=db,
                        platform=platform,
                        group=configured_group,
                        rate_multiplier=item.rate_multiplier,
                        rpm_limit=item.rpm_limit,
                        error=item.error,
                        checked_at=checked_at,
                    )
                    if change is not None:
                        rate_changes.append(change)
            if item.error:
                errors.append(f"group {item.name}: {item.error}")
                logger.warning(
                    "rate monitor discovered group failed platform_id=%s group_id=%s group_name=%s error=%s",
                    platform.id,
                    item.external_group_id,
                    item.name,
                    item.error,
                )

    recorded_group_ids: set[int] = set()
    if discovered_catalog is not None:
        configured_group_lookup = {group.external_group_id: group for group in platform.group_monitors}
        for item in discovered_groups.values():
            configured_group = configured_group_lookup.get(item.external_group_id)
            if configured_group is None or not configured_group.enabled:
                continue
            recorded_group_ids.add(configured_group.id)

    for group in platform.group_monitors:
        if not group.enabled or group.id in recorded_group_ids:
            continue
        checked_at = utcnow()
        try:
            result = await strategy.fetch_group_rate(platform, group)
            change = record_configured_group_rate(
                db=db,
                platform=platform,
                group=group,
                rate_multiplier=result.rate_multiplier,
                rpm_limit=result.rpm_limit,
                error=result.error,
                checked_at=checked_at,
            )
            if change is not None:
                rate_changes.append(change)
            if result.error:
                errors.append(f"group {group.name}: {result.error}")
                logger.warning(
                    "rate monitor configured group failed platform_id=%s group_id=%s group_name=%s error=%s",
                    platform.id,
                    group.external_group_id,
                    group.name,
                    result.error,
                )
            else:
                logger.debug(
                    "rate monitor configured group done platform_id=%s group_id=%s group_name=%s rate_multiplier=%s rpm_limit=%s",
                    platform.id,
                    group.external_group_id,
                    group.name,
                    result.rate_multiplier,
                    result.rpm_limit,
                )
        except Exception as exc:  # noqa: BLE001
            record_configured_group_rate(
                db=db,
                platform=platform,
                group=group,
                rate_multiplier=None,
                rpm_limit=None,
                error=str(exc),
                checked_at=checked_at,
            )
            errors.append(f"group {group.name}: {exc}")
            logger.exception(
                "rate monitor configured group exception platform_id=%s group_id=%s group_name=%s",
                platform.id,
                group.external_group_id,
                group.name,
            )

    now = utcnow()
    platform.rate_last_run_at = now
    platform.rate_next_run_at = croniter(platform.rate_cron, now).get_next(type(now))
    notify_group_rate_changes(db, platform, rate_changes)
    update_platform_status(platform, errors)
    db.add(platform)
    db.commit()
    db.refresh(platform)
    logger.info(
        "rate monitor done platform_id=%s name=%s status=%s errors=%s elapsed_ms=%s",
        platform.id,
        platform.name,
        platform.status,
        len(errors),
        int((monotonic() - started_at) * 1000),
    )
    return platform


def update_platform_status(platform: RelayPlatform, errors: list[str]) -> None:
    platform.checked_at = utcnow()
    platform.last_error = "\n".join(errors) if errors else None
    platform.status = PlatformStatus.degraded if errors else PlatformStatus.healthy


def sync_key_group_monitors(
    db: Session,
    platform: RelayPlatform,
    key_groups: list[KeyGroupMonitorResult] | None = None,
) -> None:
    candidates = (
        key_group_monitor_candidates_from_results(key_groups)
        if key_groups is not None
        else key_group_monitor_candidates(platform.account_monitors)
    )
    if not candidates:
        return

    existing_groups = {group.external_group_id: group for group in platform.group_monitors}
    changed = False
    for external_group_id, name in candidates.items():
        existing_group = existing_groups.get(external_group_id)
        if existing_group is not None:
            default_names = {external_group_id, f"分组 {external_group_id}"}
            if existing_group.name in default_names and existing_group.name != name:
                existing_group.name = name
                db.add(existing_group)
                changed = True
            continue

        group = PlatformGroupMonitor(
            platform_id=platform.id,
            name=name,
            external_group_id=external_group_id,
            enabled=True,
        )
        platform.group_monitors.append(group)
        db.add(group)
        existing_groups[external_group_id] = group
        changed = True

    if changed:
        db.flush()


def key_group_monitor_candidates(
    accounts: list[PlatformAccountMonitor],
) -> dict[str, str]:
    candidates: dict[str, str] = {}
    for account in accounts:
        if not account.enabled:
            continue
        for key_summary in account.key_summaries:
            external_group_id = (key_summary.get("group_id") or "").strip()
            if not external_group_id or external_group_id == "0":
                continue
            name = (key_summary.get("group_name") or f"分组 {external_group_id}").strip()
            candidates.setdefault(external_group_id, name[:120] or f"分组 {external_group_id}")
    return candidates


def key_group_monitor_candidates_from_results(
    key_groups: list[KeyGroupMonitorResult],
) -> dict[str, str]:
    candidates: dict[str, str] = {}
    for key_group in key_groups:
        external_group_id = key_group.external_group_id.strip()
        if not external_group_id or external_group_id == "0":
            continue
        name = key_group.name.strip() or f"分组 {external_group_id}"
        candidates.setdefault(external_group_id, name[:120])
    return candidates


def get_platform_detail(db: Session, platform_id: int) -> RelayPlatform | None:
    return db.scalar(
        select(RelayPlatform)
        .options(
            selectinload(RelayPlatform.account_monitors),
            selectinload(RelayPlatform.group_monitors),
            selectinload(RelayPlatform.discovered_group_rates),
            selectinload(RelayPlatform.discovered_channel_rates),
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


def record_discovered_channel_rate(
    db: Session,
    platform: RelayPlatform,
    external_channel_id: str,
    name: str,
    description: str | None,
    base_url: str | None,
    status: str | None,
    rate_multiplier: float | None,
    model_rates: dict[str, float] | None,
    error: str | None,
    checked_at: datetime | None = None,
) -> None:
    if checked_at is None:
        checked_at = utcnow()
    channel_rate = PlatformDiscoveredChannelRate(
        platform_id=platform.id,
        external_channel_id=external_channel_id,
        name=name,
        description=description,
        base_url=base_url,
        status=status,
        rate_multiplier=rate_multiplier,
        last_error=error,
        checked_at=checked_at,
    )
    channel_rate.model_rates = model_rates
    db.add(channel_rate)


def record_configured_group_rate(
    db: Session,
    platform: RelayPlatform,
    group: PlatformGroupMonitor,
    rate_multiplier: float | None,
    rpm_limit: int | None,
    error: str | None,
    checked_at: datetime | None = None,
) -> GroupRateChange | None:
    if checked_at is None:
        checked_at = utcnow()
    previous_rate = group.rate_multiplier
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
    if error or previous_rate is None or rate_multiplier is None:
        return None
    if abs(previous_rate - rate_multiplier) <= 0.000000001:
        return None
    return GroupRateChange(
        group_name=group.name,
        external_group_id=group.external_group_id,
        old_rate=previous_rate,
        new_rate=rate_multiplier,
        rpm_limit=rpm_limit,
    )
