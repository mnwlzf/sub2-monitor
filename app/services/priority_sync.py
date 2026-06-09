import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Sub2APIDatabaseSettings, Sub2APISettings
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
from app.services.sub2api_admin import Sub2APIAdminClient, Sub2APIAdminSettings
from app.services.sub2api_database import target_database_label
from app.services.sub2api_schedulable import (
    account_base_urls,
    account_id,
    account_name,
    bulk_success_ids,
    matches_platform_base_url,
)

logger = logging.getLogger(__name__)

PRIORITY_SYNC_OPERATION = "sync_account_priority"
PRIORITY_SYNC_PRIORITY_STEP = 5
PRIORITY_SYNC_ACCOUNT_LOOKUP_SQL = """
SELECT
    id,
    name,
    platform,
    type,
    status,
    schedulable,
    priority,
    CASE
        WHEN trim(trailing '/' FROM coalesce(credentials->>'base_url', '')) = trim(trailing '/' FROM %(base_url)s)
            THEN trim(trailing '/' FROM coalesce(credentials->>'base_url', ''))
        ELSE trim(trailing '/' FROM coalesce(extra->>'custom_base_url', ''))
    END AS matched_base_url
FROM accounts
WHERE deleted_at IS NULL
  AND (
    trim(trailing '/' FROM coalesce(credentials->>'base_url', '')) = trim(trailing '/' FROM %(base_url)s)
    OR (
      coalesce(extra->>'custom_base_url_enabled', 'false') = 'true'
      AND trim(trailing '/' FROM coalesce(extra->>'custom_base_url', '')) = trim(trailing '/' FROM %(base_url)s)
    )
  )
ORDER BY id ASC
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
                    "error_message": str(exc),
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
    sub2api_settings: Sub2APISettings | None = None,
    user: User | None = None,
) -> Sub2APIPrioritySyncRun:
    refresh_results = await refresh_enabled_platforms_for_priority_sync(db)
    if sub2api_settings is not None:
        from app.services.sub2api_schedulable import (
            record_sub2api_monitor_failure,
            record_sub2api_monitor_success,
        )

        for item in refresh_results:
            if item["status"] == "failed":
                await record_sub2api_monitor_failure(
                    db,
                    platform_id=int(item["platform_id"]),
                    platform_name=item.get("platform_name"),
                    base_url=str(item.get("base_url") or ""),
                    error_message=refresh_error_detail(item),
                    settings=sub2api_settings,
                )
            else:
                await record_sub2api_monitor_success(
                    db,
                    platform_id=int(item["platform_id"]),
                    platform_name=item.get("platform_name"),
                    base_url=str(item.get("base_url") or ""),
                    settings=sub2api_settings,
                )
    failed_refreshes = [item for item in refresh_results if item["status"] == "failed"]
    excluded_platforms = {
        int(item["platform_id"]): refresh_error_detail(item) for item in failed_refreshes
    }
    run = await sync_sub2api_account_priorities(
        db,
        database=database,
        sub2api_settings=sub2api_settings,
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
    target: str,
    items: list[dict[str, Any]],
    user: User | None = None,
) -> Sub2APIPrioritySyncRun:
    run = Sub2APIPrioritySyncRun(
        target_database=target,
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


def fail_planned_priority_items(items: list[dict[str, Any]], error_message: str) -> None:
    for item in items:
        if item["status"] != "planned":
            continue
        item["status"] = "failed"
        item["error_message"] = error_message
        item["change_reason"] = error_message


def priority_sync_target_label(
    *,
    database: Sub2APIDatabaseSettings,
    sub2api_settings: Sub2APISettings | None,
) -> str:
    base_url = (sub2api_settings.admin_base_url if sub2api_settings else None) or ""
    if base_url.strip():
        return f"Sub2API Admin API ({base_url.strip().rstrip('/')})"
    return target_database_label(database)


def load_priority_sync_target_accounts(
    database: Sub2APIDatabaseSettings,
    normalized_base_url: str,
) -> list[dict[str, Any]]:
    if not database.is_configured:
        raise RuntimeError("Sub2API database is not configured; cannot resolve account IDs")

    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is not installed") from exc

    with psycopg.connect(
        database.postgresql_dsn(),
        connect_timeout=database.connect_timeout_seconds,
    ) as conn:
        conn.read_only = True
        with conn.cursor() as cursor:
            cursor.execute(PRIORITY_SYNC_ACCOUNT_LOOKUP_SQL, {"base_url": normalized_base_url})
            rows = cursor.fetchall()

    return [
        {
            "id": int(row[0]),
            "name": row[1],
            "platform": row[2],
            "type": row[3],
            "status": row[4],
            "schedulable": row[5],
            "priority_before": row[6],
            "matched_base_url": normalize_base_url(row[7]),
            "account_base_urls": [normalize_base_url(row[7])] if row[7] else [],
            "lookup_source": "database",
        }
        for row in rows
    ]


async def sync_sub2api_account_priorities(
    db: Session,
    *,
    database: Sub2APIDatabaseSettings,
    sub2api_settings: Sub2APISettings | None = None,
    user: User | None = None,
    excluded_platforms: dict[int, str] | None = None,
) -> Sub2APIPrioritySyncRun:
    items = build_priority_sync_plan(db, excluded_platforms=excluded_platforms)
    run = create_priority_sync_run(
        db,
        target=priority_sync_target_label(database=database, sub2api_settings=sub2api_settings),
        items=items,
        user=user,
    )
    planned_items = [item for item in items if item["status"] == "planned"]
    if not planned_items:
        return finish_priority_sync_run(db, run, items=items, status="skipped")

    admin_settings = Sub2APIAdminSettings(
        base_url=sub2api_settings.admin_base_url if sub2api_settings else None,
        api_key=sub2api_settings.admin_api_key if sub2api_settings else None,
    )
    if not admin_settings.is_configured:
        error_message = "Sub2API Admin API is not configured"
        fail_planned_priority_items(items, error_message)
        return finish_priority_sync_run(
            db,
            run,
            items=items,
            status="failed",
            error_message=error_message,
        )

    client = Sub2APIAdminClient(admin_settings)
    admin_accounts: list[dict[str, Any]] | None = None

    for item in planned_items:
        item["change_reason"] = priority_change_reason(item)
        item["admin_api_method"] = "POST"
        item["admin_api_path"] = "/api/v1/admin/accounts/bulk-update"
        item["account_lookup_source"] = "database"
        try:
            matching_accounts = load_priority_sync_target_accounts(
                database,
                item["normalized_base_url"],
            )
        except Exception as exc:  # noqa: BLE001
            if admin_accounts is None:
                try:
                    admin_accounts = await client.list_accounts()
                except Exception:
                    admin_accounts = None
            if admin_accounts is None:
                error = str(exc)
                item["status"] = "failed"
                item["error_message"] = error
                item["change_reason"] = f"账号 ID 查询失败：{error}"
                item["matched_account_items"] = []
                item["matched_accounts"] = 0
                item["updated_accounts"] = 0
                item["updated_account_ids"] = []
                item["failed_account_ids"] = []
                item["admin_api_payload"] = None
                item["admin_api_response"] = None
                continue
            item["account_lookup_source"] = "admin_api_list_fallback"
            matching_accounts = [
                sub2api_account_summary(account, item["normalized_base_url"])
                for account in admin_accounts
                if matches_platform_base_url(account, item["normalized_base_url"])
                and account_id(account) is not None
            ]
        item["matched_account_items"] = matching_accounts
        target_ids = [
            int(account["id"])
            for account in matching_accounts
            if isinstance(account.get("id"), int)
        ]
        item["matched_accounts"] = len(target_ids)
        item["admin_api_payload"] = {"account_ids": target_ids, "priority": item["priority"]}
        if not target_ids:
            item["status"] = "succeeded"
            item["updated_accounts"] = 0
            item["updated_account_ids"] = []
            item["failed_account_ids"] = []
            item["admin_api_response"] = None
            continue
        try:
            result = await client.bulk_update_accounts(
                target_ids,
                {"priority": item["priority"]},
            )
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            item["status"] = "failed"
            item["error_message"] = error
            item["admin_api_response"] = {"error": error}
            item["updated_account_ids"] = []
            item["failed_account_ids"] = target_ids
            logger.exception(
                "sub2api priority sync item failed run_id=%s platform_id=%s base_url=%s",
                run.id,
                item["platform_id"],
                item["normalized_base_url"],
            )
            continue

        success_ids = bulk_success_ids(result, target_ids)
        failed_ids = [account_id_value for account_id_value in target_ids if account_id_value not in success_ids]
        item["updated_accounts"] = len(success_ids)
        item["updated_account_ids"] = sorted(success_ids)
        item["failed_account_ids"] = failed_ids
        item["admin_api_response"] = result
        if int(result.get("failed") or 0) > 0:
            item["status"] = "failed" if not success_ids else "succeeded"
            item["error_message"] = (
                "Sub2API Admin API bulk-update partially failed"
                if success_ids
                else "Sub2API Admin API bulk-update failed"
            )
            continue
        item["status"] = "succeeded"

    status = "succeeded"
    if any(item["status"] == "failed" for item in items):
        status = "failed" if not any(item["status"] == "succeeded" for item in items) else "partial"
    return finish_priority_sync_run(db, run, items=items, status=status)


def priority_change_reason(item: dict[str, Any]) -> str:
    group = item.get("selected_group")
    group_label = ""
    if isinstance(group, dict):
        group_name = str(group.get("name") or group.get("external_group_id") or "").strip()
        effective_rate = group.get("effective_rate_multiplier")
        if group_name:
            group_label = f"，最低有效倍率分组：{group_name}（{effective_rate}）"
    return (
        f"按启用账号绑定分组的有效倍率排序，平台 {item['platform_name']} "
        f"获得 Priority {item['priority']}{group_label}"
    )


def sub2api_account_summary(account: dict[str, Any], matched_base_url: str) -> dict[str, Any]:
    return {
        "id": account_id(account),
        "name": account_name(account),
        "platform": account.get("platform"),
        "type": account.get("type"),
        "status": account.get("status"),
        "schedulable": account.get("schedulable"),
        "priority_before": account.get("priority"),
        "matched_base_url": matched_base_url,
        "account_base_urls": sorted(account_base_urls(account)),
    }
