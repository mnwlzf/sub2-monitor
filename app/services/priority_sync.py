import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Sub2APIDatabaseSettings
from app.core.security import utcnow
from app.models.monitor import (
    PlatformAccountMonitor,
    PlatformDiscoveredGroupRate,
    PlatformGroupMonitor,
)
from app.models.platform import RelayPlatform
from app.models.sub2api import Sub2APIPrioritySyncRun
from app.models.user import User
from app.services.monitoring import run_platform_monitor
from app.services.sub2api_database import (
    create_sql_log,
    target_database_label,
    update_sql_log_result,
)

logger = logging.getLogger(__name__)

PRIORITY_SYNC_OPERATION = "sync_account_priority"
PRIORITY_SYNC_TARGET_DATABASE = "sub2api"
PRIORITY_SYNC_PRIORITY_STEP = 5
PRIORITY_SYNC_SQL = """
WITH matched AS (
    SELECT id
    FROM accounts
    WHERE deleted_at IS NULL
      AND (
        trim(trailing '/' FROM coalesce(credentials->>'base_url', '')) = trim(trailing '/' FROM %(base_url)s)
        OR (
          coalesce(extra->>'custom_base_url_enabled', 'false') = 'true'
          AND trim(trailing '/' FROM coalesce(extra->>'custom_base_url', '')) = trim(trailing '/' FROM %(base_url)s)
        )
      )
),
updated AS (
    UPDATE accounts
    SET priority = %(priority)s
    WHERE id IN (SELECT id FROM matched)
    RETURNING id
)
SELECT
    (SELECT count(*) FROM matched) AS matched_accounts,
    (SELECT count(*) FROM updated) AS updated_accounts
"""


def platform_label(item: dict[str, Any]) -> str:
    name = str(item.get("platform_name") or "").strip()
    base_url = normalize_base_url(item.get("base_url"))
    platform_id = item.get("platform_id")
    label = name or f"平台 #{platform_id}"
    return f"{label}（{base_url}）" if base_url else label


def refresh_error_detail(item: dict[str, Any]) -> str:
    error = str(item.get("error_message") or "未提供错误详情").strip()
    return f"{platform_label(item)}：{error}"


def priority_sync_database_error(database: Sub2APIDatabaseSettings) -> str | None:
    configured_dbname = (database.dbname or "").strip()
    if database.dsn:
        from urllib.parse import urlsplit

        configured_dbname = urlsplit(database.dsn).path.strip("/") or configured_dbname
    if configured_dbname and configured_dbname != PRIORITY_SYNC_TARGET_DATABASE:
        return (
            "Sub2API account priority sync must target database "
            f"{PRIORITY_SYNC_TARGET_DATABASE!r}, got {configured_dbname!r}"
        )
    return None


async def refresh_enabled_platforms_for_priority_sync(db: Session) -> list[dict[str, Any]]:
    platforms = list(
        db.scalars(
            select(RelayPlatform)
            .where(RelayPlatform.enabled.is_(True))
            .order_by(RelayPlatform.id.asc())
        ).all()
    )
    results: list[dict[str, Any]] = []
    for platform in platforms:
        try:
            platform = await run_platform_monitor(db, platform.id)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception("priority sync pre-refresh failed platform_id=%s", platform.id)
            results.append(
                {
                    "platform_id": platform.id,
                    "platform_name": platform.name,
                    "base_url": platform.base_url,
                    "status": "failed",
                    "error_message": str(exc) or exc.__class__.__name__,
                }
            )
            continue
        if platform.last_error:
            results.append(
                {
                    "platform_id": platform.id,
                    "platform_name": platform.name,
                    "base_url": platform.base_url,
                    "status": "failed",
                    "error_message": platform.last_error,
                }
            )
            continue
        results.append(
            {
                "platform_id": platform.id,
                "platform_name": platform.name,
                "base_url": platform.base_url,
                "status": "succeeded",
                "error_message": None,
            }
        )
    return results


async def refresh_and_sync_sub2api_account_priorities(
    db: Session,
    *,
    database: Sub2APIDatabaseSettings,
    user: User | None = None,
) -> Sub2APIPrioritySyncRun:
    refresh_results = await refresh_enabled_platforms_for_priority_sync(db)
    failed_refreshes = [item for item in refresh_results if item["status"] == "failed"]
    excluded_platforms = {
        int(item["platform_id"]): refresh_error_detail(item) for item in failed_refreshes
    }
    run = sync_sub2api_account_priorities(
        db,
        database=database,
        user=user,
        excluded_platforms=excluded_platforms,
    )
    if failed_refreshes:
        refresh_error = "部分平台预采集失败，已从本次 Priority 排序中剔除：" + "；".join(
            refresh_error_detail(item) for item in failed_refreshes
        )
        run.error_message = (
            f"{run.error_message}\n{refresh_error}" if run.error_message else refresh_error
        )
        if run.status in {"succeeded", "skipped"}:
            run.status = "partial"
        db.add(run)
        db.commit()
        db.refresh(run)
    return run


def normalize_base_url(value: str | None) -> str:
    return (value or "").strip().rstrip("/")


def priority_sql_params(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "base_url": item["normalized_base_url"],
        "priority": item["priority"],
    }


def load_priority_sync_platforms(db: Session) -> list[RelayPlatform]:
    return list(
        db.scalars(
            select(RelayPlatform)
            .options(
                selectinload(RelayPlatform.account_monitors),
                selectinload(RelayPlatform.group_monitors),
                selectinload(RelayPlatform.discovered_group_rates),
            )
            .where(RelayPlatform.enabled.is_(True))
            .order_by(RelayPlatform.id.asc())
        ).all()
    )


def key_group_ids_from_accounts(accounts: list[PlatformAccountMonitor]) -> dict[str, str]:
    group_names: dict[str, str] = {}
    for account in accounts:
        if not account.enabled:
            continue
        for summary in account.key_summaries:
            external_group_id = (summary.get("group_id") or "").strip()
            if not external_group_id or external_group_id == "0":
                continue
            group_name = (summary.get("group_name") or f"分组 {external_group_id}").strip()
            group_names.setdefault(external_group_id, group_name or f"分组 {external_group_id}")
    return group_names


def configured_group_lookup(
    groups: list[PlatformGroupMonitor],
) -> dict[str, PlatformGroupMonitor]:
    return {group.external_group_id: group for group in groups if group.enabled}


def discovered_group_lookup(
    groups: list[PlatformDiscoveredGroupRate],
) -> dict[str, PlatformDiscoveredGroupRate]:
    lookup: dict[str, PlatformDiscoveredGroupRate] = {}
    for group in groups:
        lookup[group.external_group_id] = group
    return lookup


def group_candidate(
    *,
    external_group_id: str,
    fallback_name: str,
    rate_factor: float | None,
    configured_groups: dict[str, PlatformGroupMonitor],
    discovered_groups: dict[str, PlatformDiscoveredGroupRate],
) -> dict[str, Any]:
    source = "configured"
    configured_group = configured_groups.get(external_group_id)
    discovered_group = discovered_groups.get(external_group_id)
    if configured_group is not None:
        name = configured_group.name
        rate_multiplier = configured_group.rate_multiplier
        rpm_limit = configured_group.rpm_limit
        last_error = configured_group.last_error
    elif discovered_group is not None:
        source = "discovered"
        name = discovered_group.name
        rate_multiplier = discovered_group.rate_multiplier
        rpm_limit = discovered_group.rpm_limit
        last_error = discovered_group.last_error
    else:
        source = "missing"
        name = fallback_name
        rate_multiplier = None
        rpm_limit = None
        last_error = "密钥分组未采集到倍率"

    effective_rate_multiplier = (
        rate_multiplier * rate_factor
        if rate_multiplier is not None and rate_factor is not None
        else None
    )
    return {
        "external_group_id": external_group_id,
        "name": name,
        "source": source,
        "rate_multiplier": rate_multiplier,
        "rate_factor": rate_factor,
        "effective_rate_multiplier": effective_rate_multiplier,
        "rpm_limit": rpm_limit,
        "last_error": last_error,
    }


def platform_priority_candidate(
    platform: RelayPlatform,
    *,
    excluded_reason: str | None = None,
) -> dict[str, Any]:
    normalized_base_url = normalize_base_url(platform.base_url)
    rate_factor = platform.effective_rate_factor
    used_group_names = key_group_ids_from_accounts(platform.account_monitors)
    configured_groups = configured_group_lookup(platform.group_monitors)
    discovered_groups = discovered_group_lookup(platform.discovered_group_rates)
    candidate_groups = [
        group_candidate(
            external_group_id=external_group_id,
            fallback_name=group_name,
            rate_factor=rate_factor,
            configured_groups=configured_groups,
            discovered_groups=discovered_groups,
        )
        for external_group_id, group_name in sorted(used_group_names.items())
    ]
    usable_groups = [
        group
        for group in candidate_groups
        if group.get("effective_rate_multiplier") is not None
    ]
    selected_group = min(
        usable_groups,
        key=lambda item: float(item["effective_rate_multiplier"]),
        default=None,
    )

    error_message: str | None = None
    if excluded_reason:
        error_message = f"本次预采集失败，已从 Priority 排序中剔除：{excluded_reason}"
    elif not normalized_base_url:
        error_message = "平台 base_url 为空"
    elif rate_factor is None:
        error_message = "平台充值金额或到账金额无效，无法计算实际倍率"
    elif not used_group_names:
        error_message = "未发现启用账号实际绑定的密钥分组"
    elif selected_group is None:
        error_message = "密钥分组尚无可用倍率"

    return {
        "platform_id": platform.id,
        "platform_name": platform.name,
        "base_url": platform.base_url,
        "normalized_base_url": normalized_base_url,
        "rate_factor": rate_factor,
        "candidate_groups": candidate_groups,
        "selected_group": selected_group,
        "effective_rate_multiplier": selected_group.get("effective_rate_multiplier")
        if selected_group
        else None,
        "priority": None,
        "status": "skipped" if error_message else "planned",
        "matched_accounts": None,
        "updated_accounts": None,
        "sql_log_id": None,
        "error_message": error_message,
    }


def dedupe_priority_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_base_url: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    for item in items:
        if item["status"] == "skipped":
            skipped.append(item)
            continue
        normalized_base_url = item["normalized_base_url"]
        existing = by_base_url.get(normalized_base_url)
        if existing is None:
            by_base_url[normalized_base_url] = item
            continue
        existing_rate = existing["effective_rate_multiplier"]
        item_rate = item["effective_rate_multiplier"]
        if item_rate is not None and (existing_rate is None or item_rate < existing_rate):
            skipped.append(
                {
                    **existing,
                    "status": "skipped",
                    "priority": None,
                    "error_message": f"同一 base_url 已由更低实际倍率平台 {item['platform_name']} 接管",
                }
            )
            by_base_url[normalized_base_url] = item
        else:
            skipped.append(
                {
                    **item,
                    "status": "skipped",
                    "priority": None,
                    "error_message": f"同一 base_url 已由更低实际倍率平台 {existing['platform_name']} 接管",
                }
            )
    return [*by_base_url.values(), *skipped]


def build_priority_sync_plan(
    db: Session,
    *,
    excluded_platforms: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    excluded_platforms = excluded_platforms or {}
    raw_items = [
        platform_priority_candidate(
            platform,
            excluded_reason=excluded_platforms.get(platform.id),
        )
        for platform in load_priority_sync_platforms(db)
    ]
    items = dedupe_priority_items(raw_items)
    planned_items = [
        item for item in items if item["status"] == "planned" and item["effective_rate_multiplier"] is not None
    ]
    planned_items.sort(
        key=lambda item: (
            float(item["effective_rate_multiplier"]),
            item["platform_name"],
            item["normalized_base_url"],
        )
    )
    for index, item in enumerate(planned_items, start=1):
        item["priority"] = index * PRIORITY_SYNC_PRIORITY_STEP
    skipped_items = [item for item in items if item["status"] == "skipped"]
    skipped_items.sort(key=lambda item: (item["platform_name"], item["normalized_base_url"]))
    return [*planned_items, *skipped_items]


def create_priority_sync_run(
    db: Session,
    *,
    database: Sub2APIDatabaseSettings,
    items: list[dict[str, Any]],
    user: User | None = None,
) -> Sub2APIPrioritySyncRun:
    run = Sub2APIPrioritySyncRun(
        target_database=target_database_label(database),
        status="pending",
        total_items=len(items),
        skipped_items=sum(1 for item in items if item["status"] == "skipped"),
        executed_by_user_id=user.id if user else None,
        executed_by_username=user.username if user else None,
    )
    run.items = items
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_priority_sync_run(
    db: Session,
    run: Sub2APIPrioritySyncRun,
    *,
    items: list[dict[str, Any]],
    status: str,
    error_message: str | None = None,
) -> Sub2APIPrioritySyncRun:
    run.status = status
    run.error_message = error_message
    run.completed_at = utcnow()
    run.total_items = len(items)
    run.succeeded_items = sum(1 for item in items if item["status"] == "succeeded")
    run.failed_items = sum(1 for item in items if item["status"] == "failed")
    run.skipped_items = sum(1 for item in items if item["status"] == "skipped")
    run.matched_accounts = sum(int(item.get("matched_accounts") or 0) for item in items)
    run.updated_accounts = sum(int(item.get("updated_accounts") or 0) for item in items)
    run.items = items
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def failed_sql_logs_for_items(
    db: Session,
    *,
    database: Sub2APIDatabaseSettings,
    items: list[dict[str, Any]],
    error_message: str,
    user: User | None = None,
) -> None:
    for item in items:
        if item["status"] != "planned":
            continue
        log = create_sql_log(
            db,
            operation=PRIORITY_SYNC_OPERATION,
            database=database,
            sql_text=PRIORITY_SYNC_SQL,
            sql_params=priority_sql_params(item),
            user=user,
        )
        update_sql_log_result(db, log, status="failed", error_message=error_message)
        item["sql_log_id"] = log.id
        item["status"] = "failed"
        item["error_message"] = error_message


def sync_sub2api_account_priorities(
    db: Session,
    *,
    database: Sub2APIDatabaseSettings,
    user: User | None = None,
    excluded_platforms: dict[int, str] | None = None,
) -> Sub2APIPrioritySyncRun:
    items = build_priority_sync_plan(db, excluded_platforms=excluded_platforms)
    run = create_priority_sync_run(db, database=database, items=items, user=user)
    planned_items = [item for item in items if item["status"] == "planned"]
    if not planned_items:
        return finish_priority_sync_run(db, run, items=items, status="skipped")

    if not database.is_configured:
        error_message = "Sub2API database is not configured"
        failed_sql_logs_for_items(
            db,
            database=database,
            items=items,
            error_message=error_message,
            user=user,
        )
        return finish_priority_sync_run(
            db,
            run,
            items=items,
            status="failed",
            error_message=error_message,
        )

    database_error = priority_sync_database_error(database)
    if database_error:
        failed_sql_logs_for_items(
            db,
            database=database,
            items=items,
            error_message=database_error,
            user=user,
        )
        return finish_priority_sync_run(
            db,
            run,
            items=items,
            status="failed",
            error_message=database_error,
        )

    try:
        import psycopg
    except ImportError:
        error_message = "psycopg is not installed"
        failed_sql_logs_for_items(
            db,
            database=database,
            items=items,
            error_message=error_message,
            user=user,
        )
        return finish_priority_sync_run(
            db,
            run,
            items=items,
            status="failed",
            error_message=error_message,
        )

    try:
        with psycopg.connect(
            database.postgresql_dsn(),
            connect_timeout=database.connect_timeout_seconds,
        ) as conn:
            for item in planned_items:
                log = create_sql_log(
                    db,
                    operation=PRIORITY_SYNC_OPERATION,
                    database=database,
                    sql_text=PRIORITY_SYNC_SQL,
                    sql_params=priority_sql_params(item),
                    user=user,
                )
                item["sql_log_id"] = log.id
                try:
                    with conn.cursor() as cursor:
                        cursor.execute(PRIORITY_SYNC_SQL, priority_sql_params(item))
                        matched_accounts, updated_accounts = cursor.fetchone()
                    conn.commit()
                except Exception as exc:  # noqa: BLE001
                    conn.rollback()
                    error = str(exc)
                    item["status"] = "failed"
                    item["error_message"] = error
                    update_sql_log_result(db, log, status="failed", error_message=error)
                    logger.exception(
                        "sub2api priority sync item failed run_id=%s platform_id=%s base_url=%s",
                        run.id,
                        item["platform_id"],
                        item["normalized_base_url"],
                    )
                    continue

                item["status"] = "succeeded"
                item["matched_accounts"] = int(matched_accounts or 0)
                item["updated_accounts"] = int(updated_accounts or 0)
                update_sql_log_result(
                    db,
                    log,
                    status="succeeded",
                    affected_rows=item["updated_accounts"],
                )
    except Exception as exc:  # noqa: BLE001
        error_message = str(exc)
        failed_sql_logs_for_items(
            db,
            database=database,
            items=items,
            error_message=error_message,
            user=user,
        )
        return finish_priority_sync_run(
            db,
            run,
            items=items,
            status="failed",
            error_message=error_message,
        )

    status = "succeeded"
    if any(item["status"] == "failed" for item in items):
        status = "failed" if not any(item["status"] == "succeeded" for item in items) else "partial"
    return finish_priority_sync_run(db, run, items=items, status=status)
