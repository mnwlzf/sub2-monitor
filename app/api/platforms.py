from bisect import bisect_right
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from croniter import croniter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import encrypt_secret, utcnow
from app.models.monitor import PlatformAccountMonitor, PlatformGroupMonitor
from app.models.platform import PlatformStatus, RelayPlatform
from app.models.snapshot import (
    AccountBalanceSnapshot,
    DiscoveredGroupRateSnapshot,
    GroupRateSnapshot,
    PlatformSnapshot,
)
from app.schemas.platform import (
    AccountBalanceHistorySeries,
    AccountMonitorCreate,
    AccountMonitorResponse,
    AccountMonitorUpdate,
    DashboardStats,
    GroupRateHistorySeries,
    GroupMonitorCreate,
    GroupMonitorResponse,
    GroupMonitorUpdate,
    MonitorRunResponse,
    PlatformCreate,
    PlatformDetailResponse,
    PlatformResponse,
    PlatformUpdate,
    SiteStrategyOption,
    ProviderOption,
    SnapshotCreate,
)
from app.services.monitoring import (
    get_platform_detail,
    run_platform_balance_monitor,
    run_platform_monitor,
    run_platform_rate_monitor,
)
from app.services.provider_strategy import newapi_site_strategy_registry, provider_registry

router = APIRouter(tags=["platforms"])


def platform_payload(payload: PlatformCreate | PlatformUpdate) -> dict:
    data = payload.model_dump(exclude_unset=True, mode="json")
    if "api_key" in data:
        api_key = data.pop("api_key")
        if api_key:
            data["api_key_encrypted"] = encrypt_secret(api_key)
    return data


def account_payload(payload: AccountMonitorCreate | AccountMonitorUpdate) -> dict:
    data = payload.model_dump(exclude_unset=True)
    if "password" in data:
        password = data.pop("password")
        if password:
            data["password_encrypted"] = encrypt_secret(password)
    return data


def update_next_run_times(platform: RelayPlatform, fields: set[str]) -> None:
    now = utcnow()
    if "balance_cron" in fields:
        platform.balance_next_run_at = croniter(platform.balance_cron, now).get_next(type(now))
    if "rate_cron" in fields:
        platform.rate_next_run_at = croniter(platform.rate_cron, now).get_next(type(now))


def validate_strategy(provider_type: str, site_strategy: str) -> None:
    provider_registry.get(provider_type)
    if provider_type == "newapi":
        newapi_site_strategy_registry.get(site_strategy)


def detail_or_404(db: Session, platform_id: int) -> RelayPlatform:
    platform = get_platform_detail(db, platform_id)
    if platform is None:
        raise HTTPException(status_code=404, detail="Platform not found")
    return platform


@router.get("/dashboard", response_model=DashboardStats)
def dashboard(db: Session = Depends(get_db)) -> DashboardStats:
    platforms = db.scalars(select(RelayPlatform)).all()
    account_monitor_count = len(db.scalars(select(PlatformAccountMonitor.id)).all())
    group_monitor_count = len(db.scalars(select(PlatformGroupMonitor.id)).all())
    latencies = [item.latency_ms for item in platforms if item.latency_ms is not None]
    return DashboardStats(
        total_platforms=len(platforms),
        enabled_platforms=sum(1 for item in platforms if item.enabled),
        healthy_platforms=sum(1 for item in platforms if item.status == PlatformStatus.healthy),
        degraded_platforms=sum(1 for item in platforms if item.status == PlatformStatus.degraded),
        down_platforms=sum(1 for item in platforms if item.status == PlatformStatus.down),
        total_keys=sum(item.key_count for item in platforms),
        account_monitor_count=account_monitor_count,
        group_monitor_count=group_monitor_count,
        average_latency_ms=round(sum(latencies) / len(latencies)) if latencies else None,
    )


@router.get("/providers", response_model=list[ProviderOption])
def provider_options() -> list[dict[str, str]]:
    return provider_registry.options()


@router.get("/site-strategies", response_model=list[SiteStrategyOption])
def site_strategy_options() -> list[dict[str, str]]:
    return newapi_site_strategy_registry.options()


@router.get("/platforms", response_model=list[PlatformResponse])
def list_platforms(db: Session = Depends(get_db)) -> list[RelayPlatform]:
    return list(db.scalars(select(RelayPlatform).order_by(RelayPlatform.created_at.desc())).all())


@router.get("/platforms/{platform_id}", response_model=PlatformDetailResponse)
def get_platform(platform_id: int, db: Session = Depends(get_db)) -> RelayPlatform:
    return detail_or_404(db, platform_id)


@router.post(
    "/platforms",
    response_model=PlatformResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_platform(payload: PlatformCreate, db: Session = Depends(get_db)) -> RelayPlatform:
    try:
        validate_strategy(payload.provider_type, payload.site_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    platform = RelayPlatform(**platform_payload(payload))
    update_next_run_times(platform, {"balance_cron", "rate_cron"})
    db.add(platform)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Platform name already exists") from exc
    db.refresh(platform)
    return platform


@router.patch(
    "/platforms/{platform_id}",
    response_model=PlatformResponse,
)
def update_platform(
    platform_id: int,
    payload: PlatformUpdate,
    db: Session = Depends(get_db),
) -> RelayPlatform:
    platform = db.get(RelayPlatform, platform_id)
    if platform is None:
        raise HTTPException(status_code=404, detail="Platform not found")
    data = platform_payload(payload)
    provider_type = data.get("provider_type", platform.provider_type)
    site_strategy = data.get("site_strategy", platform.site_strategy)
    try:
        validate_strategy(provider_type, site_strategy)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    for field, value in data.items():
        setattr(platform, field, value)
    update_next_run_times(platform, set(data))
    db.add(platform)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Platform name already exists") from exc
    db.refresh(platform)
    return platform


@router.delete("/platforms/{platform_id}")
def delete_platform(platform_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    platform = db.get(RelayPlatform, platform_id)
    if platform is None:
        raise HTTPException(status_code=404, detail="Platform not found")
    db.delete(platform)
    db.commit()
    return {"ok": True}


@router.post(
    "/platforms/{platform_id}/monitor/run",
    response_model=MonitorRunResponse,
)
async def run_monitor(platform_id: int, db: Session = Depends(get_db)) -> MonitorRunResponse:
    try:
        platform = await run_platform_monitor(db, platform_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Platform not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    detail = detail_or_404(db, platform.id)
    return {
        "platform": detail,
        "account_monitors": detail.account_monitors,
        "group_monitors": detail.group_monitors,
    }


@router.post(
    "/platforms/{platform_id}/monitor/balance/run",
    response_model=MonitorRunResponse,
)
async def run_balance_monitor(platform_id: int, db: Session = Depends(get_db)) -> MonitorRunResponse:
    try:
        platform = await run_platform_balance_monitor(db, platform_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Platform not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    detail = detail_or_404(db, platform.id)
    return {
        "platform": detail,
        "account_monitors": detail.account_monitors,
        "group_monitors": detail.group_monitors,
    }


@router.post(
    "/platforms/{platform_id}/monitor/rate/run",
    response_model=MonitorRunResponse,
)
async def run_rate_monitor(platform_id: int, db: Session = Depends(get_db)) -> MonitorRunResponse:
    try:
        platform = await run_platform_rate_monitor(db, platform_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Platform not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    detail = detail_or_404(db, platform.id)
    return {
        "platform": detail,
        "account_monitors": detail.account_monitors,
        "group_monitors": detail.group_monitors,
    }


@router.get(
    "/platforms/{platform_id}/history/balances",
    response_model=list[AccountBalanceHistorySeries],
)
def get_balance_history(
    platform_id: int,
    db: Session = Depends(get_db),
) -> list[AccountBalanceHistorySeries]:
    platform = detail_or_404(db, platform_id)
    now = utcnow()
    since = now - timedelta(days=1)
    snapshots = db.scalars(
        select(AccountBalanceSnapshot)
        .where(
            AccountBalanceSnapshot.platform_id == platform_id,
            AccountBalanceSnapshot.created_at >= since,
        )
        .order_by(AccountBalanceSnapshot.created_at.asc())
    ).all()
    by_account: dict[int, list[AccountBalanceSnapshot]] = {}
    for snapshot in snapshots:
        by_account.setdefault(snapshot.account_monitor_id, []).append(snapshot)

    return [
        AccountBalanceHistorySeries(
            account_id=account.id,
            account_name=account.name,
            points=build_account_balance_points(by_account.get(account.id, [])),
        )
        for account in platform.account_monitors
    ]


@router.get(
    "/platforms/{platform_id}/history/rates",
    response_model=list[GroupRateHistorySeries],
)
def get_rate_history(
    platform_id: int,
    db: Session = Depends(get_db),
) -> list[GroupRateHistorySeries]:
    platform = detail_or_404(db, platform_id)
    effective_rate_factor = platform.effective_rate_factor
    now = utcnow()
    since = now - timedelta(days=7)
    ticks = build_history_ticks(platform.rate_cron, since, now)
    start = ticks[0]

    discovered_snapshots = db.scalars(
        select(DiscoveredGroupRateSnapshot)
        .where(
            DiscoveredGroupRateSnapshot.platform_id == platform_id,
            DiscoveredGroupRateSnapshot.created_at >= start,
        )
        .order_by(DiscoveredGroupRateSnapshot.created_at.asc())
    ).all()
    by_external_group_id: dict[str, list[DiscoveredGroupRateSnapshot]] = {}
    for snapshot in discovered_snapshots:
        by_external_group_id.setdefault(snapshot.external_group_id, []).append(snapshot)
    group_snapshots = db.scalars(
        select(GroupRateSnapshot)
        .where(
            GroupRateSnapshot.platform_id == platform_id,
            GroupRateSnapshot.created_at >= start,
        )
        .order_by(GroupRateSnapshot.created_at.asc())
    ).all()
    by_group_monitor_id: dict[int, list[GroupRateSnapshot]] = {}
    for snapshot in group_snapshots:
        by_group_monitor_id.setdefault(snapshot.group_monitor_id, []).append(snapshot)

    configured_groups = {
        group.external_group_id: group
        for group in platform.group_monitors
    }

    if platform.discovered_group_rates:
        return [
            GroupRateHistorySeries(
                group_id=configured_groups.get(group.external_group_id).id
                if group.external_group_id in configured_groups
                else None,
                external_group_id=group.external_group_id,
                group_name=group.name,
                description=group.description,
                configured_monitor_id=configured_groups.get(group.external_group_id).id
                if group.external_group_id in configured_groups
                else None,
                is_configured=group.external_group_id in configured_groups,
                points=build_discovered_rate_points(
                    ticks,
                    by_external_group_id.get(group.external_group_id, []),
                    effective_rate_factor,
                ),
            )
            for group in platform.discovered_group_rates
        ]

    return [
        GroupRateHistorySeries(
            group_id=group.id,
            external_group_id=group.external_group_id,
            group_name=group.name,
            description=None,
            configured_monitor_id=group.id,
            is_configured=True,
            points=build_rate_points(
                ticks,
                by_group_monitor_id.get(group.id, []),
                effective_rate_factor,
            ),
        )
        for group in platform.group_monitors
    ]


def build_history_ticks(cron_expr: str, since: datetime, until: datetime) -> list[datetime]:
    first_tick = croniter(cron_expr, since).get_prev(datetime)
    ticks = [first_tick]
    iterator = croniter(cron_expr, first_tick)
    while True:
        next_tick = iterator.get_next(datetime)
        if next_tick > until:
            break
        ticks.append(next_tick)
    return ticks


def build_account_balance_points(
    snapshots: list[AccountBalanceSnapshot],
) -> list[dict]:
    return [
        {
            "at": snapshot.created_at,
            "balance": snapshot.balance,
            "quota_used": snapshot.quota_used,
            "quota_limit": snapshot.quota_limit,
        }
        for snapshot in snapshots
    ]


def build_rate_points(
    ticks: list[datetime],
    snapshots: list[GroupRateSnapshot],
    effective_rate_factor: float | None,
) -> list[dict]:
    snapshots_by_tick: dict[datetime, GroupRateSnapshot] = {}
    for snapshot in snapshots:
        tick_index = bisect_right(ticks, snapshot.created_at) - 1
        if tick_index >= 0:
            snapshots_by_tick[ticks[tick_index]] = snapshot

    return [
        {
            "at": tick,
            "rate_multiplier": (
                snapshots_by_tick[tick].rate_multiplier if tick in snapshots_by_tick else None
            ),
            "effective_rate_multiplier": (
                snapshots_by_tick[tick].rate_multiplier * effective_rate_factor
                if tick in snapshots_by_tick
                and snapshots_by_tick[tick].rate_multiplier is not None
                and effective_rate_factor is not None
                else None
            ),
            "rpm_limit": snapshots_by_tick[tick].rpm_limit if tick in snapshots_by_tick else None,
        }
        for tick in ticks
    ]


def build_discovered_rate_points(
    ticks: list[datetime],
    snapshots: list[DiscoveredGroupRateSnapshot],
    effective_rate_factor: float | None,
) -> list[dict]:
    snapshots_by_tick: dict[datetime, DiscoveredGroupRateSnapshot] = {}
    for snapshot in snapshots:
        tick_index = bisect_right(ticks, snapshot.created_at) - 1
        if tick_index >= 0:
            snapshots_by_tick[ticks[tick_index]] = snapshot

    return [
        {
            "at": tick,
            "rate_multiplier": (
                snapshots_by_tick[tick].rate_multiplier if tick in snapshots_by_tick else None
            ),
            "effective_rate_multiplier": (
                snapshots_by_tick[tick].rate_multiplier * effective_rate_factor
                if tick in snapshots_by_tick
                and snapshots_by_tick[tick].rate_multiplier is not None
                and effective_rate_factor is not None
                else None
            ),
            "rpm_limit": snapshots_by_tick[tick].rpm_limit if tick in snapshots_by_tick else None,
        }
        for tick in ticks
    ]


@router.post(
    "/platforms/{platform_id}/accounts",
    response_model=AccountMonitorResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_account_monitor(
    platform_id: int,
    payload: AccountMonitorCreate,
    db: Session = Depends(get_db),
) -> PlatformAccountMonitor:
    detail_or_404(db, platform_id)
    item = PlatformAccountMonitor(platform_id=platform_id, **account_payload(payload))
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch(
    "/platforms/{platform_id}/accounts/{monitor_id}",
    response_model=AccountMonitorResponse,
)
def update_account_monitor(
    platform_id: int,
    monitor_id: int,
    payload: AccountMonitorUpdate,
    db: Session = Depends(get_db),
) -> PlatformAccountMonitor:
    item = db.scalar(
        select(PlatformAccountMonitor).where(
            PlatformAccountMonitor.id == monitor_id,
            PlatformAccountMonitor.platform_id == platform_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Account monitor not found")
    for field, value in account_payload(payload).items():
        setattr(item, field, value)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/platforms/{platform_id}/accounts/{monitor_id}",
)
def delete_account_monitor(platform_id: int, monitor_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    item = db.scalar(
        select(PlatformAccountMonitor).where(
            PlatformAccountMonitor.id == monitor_id,
            PlatformAccountMonitor.platform_id == platform_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Account monitor not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post(
    "/platforms/{platform_id}/groups",
    response_model=GroupMonitorResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_group_monitor(
    platform_id: int,
    payload: GroupMonitorCreate,
    db: Session = Depends(get_db),
) -> PlatformGroupMonitor:
    detail_or_404(db, platform_id)
    item = PlatformGroupMonitor(platform_id=platform_id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch(
    "/platforms/{platform_id}/groups/{monitor_id}",
    response_model=GroupMonitorResponse,
)
def update_group_monitor(
    platform_id: int,
    monitor_id: int,
    payload: GroupMonitorUpdate,
    db: Session = Depends(get_db),
) -> PlatformGroupMonitor:
    item = db.scalar(
        select(PlatformGroupMonitor).where(
            PlatformGroupMonitor.id == monitor_id,
            PlatformGroupMonitor.platform_id == platform_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Group monitor not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/platforms/{platform_id}/groups/{monitor_id}",
)
def delete_group_monitor(platform_id: int, monitor_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    item = db.scalar(
        select(PlatformGroupMonitor).where(
            PlatformGroupMonitor.id == monitor_id,
            PlatformGroupMonitor.platform_id == platform_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Group monitor not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post(
    "/platforms/{platform_id}/snapshots",
    response_model=PlatformResponse,
)
def add_platform_snapshot(
    platform_id: int,
    payload: SnapshotCreate,
    db: Session = Depends(get_db),
) -> RelayPlatform:
    platform = db.get(RelayPlatform, platform_id)
    if platform is None:
        raise HTTPException(status_code=404, detail="Platform not found")
    snapshot = PlatformSnapshot(platform_id=platform.id, **payload.model_dump(mode="json"))
    platform.status = payload.status
    platform.balance = payload.balance
    platform.quota_used = payload.quota_used
    platform.quota_limit = payload.quota_limit
    platform.latency_ms = payload.latency_ms
    platform.last_error = payload.error_message
    platform.checked_at = utcnow()
    db.add(snapshot)
    db.add(platform)
    db.commit()
    db.refresh(platform)
    return platform
