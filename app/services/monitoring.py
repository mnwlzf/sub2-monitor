import asyncio
import json
import logging
import ssl
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from urllib.parse import urlsplit

from croniter import croniter
import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.security import decrypt_secret
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
    PlatformSnapshot,
)
from app.services.notification import (
    GroupCatalogChange,
    GroupRateChange,
    notify_group_rate_changes,
    notify_low_balance,
)
from app.services.provider_strategy import (
    DiscoveredChannelRateResult,
    DiscoveredGroupRateResult,
    KeyGroupMonitorResult,
    provider_registry,
)
from app.core.config import get_settings
from app.services.sub2api_proxy import load_platform_proxy_urls, masked_proxy_url
from app.services.sub2api_schedulable import normalize_base_url

logger = logging.getLogger(__name__)

MONITOR_MAX_ATTEMPTS = 3
MONITOR_RETRY_DELAY_SECONDS = 5
CONNECT_LATENCY_TIMEOUT_SECONDS = 5.0
MODEL_TEST_TIMEOUT_SECONDS = 30.0
MODEL_TEST_PROMPT = "hi"


@dataclass(frozen=True)
class GroupCatalogItem:
    external_group_id: str
    name: str
    rate_multiplier: float | None
    rpm_limit: int | None


@dataclass(frozen=True)
class ModelFirstTokenResult:
    first_token_ms: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class Sub2APIModelTestAccount:
    account_id: int
    account_name: str | None
    api_key: str
    matched_base_url: str


SUB2API_MODEL_TEST_ACCOUNT_SQL = """
SELECT
    id,
    name,
    credentials,
    CASE
        WHEN trim(trailing '/' FROM coalesce(credentials->>'base_url', '')) = trim(trailing '/' FROM %(base_url)s)
            THEN trim(trailing '/' FROM coalesce(credentials->>'base_url', ''))
        ELSE trim(trailing '/' FROM coalesce(extra->>'custom_base_url', ''))
    END AS matched_base_url
FROM accounts
WHERE deleted_at IS NULL
  AND trim(coalesce(credentials->>'api_key', '')) <> ''
  AND (
    trim(trailing '/' FROM coalesce(credentials->>'base_url', '')) = trim(trailing '/' FROM %(base_url)s)
    OR (
      coalesce(extra->>'custom_base_url_enabled', 'false') = 'true'
      AND trim(trailing '/' FROM coalesce(extra->>'custom_base_url', '')) = trim(trailing '/' FROM %(base_url)s)
    )
  )
ORDER BY id ASC
LIMIT 1
"""


def error_text(error: BaseException | str | None) -> str:
    def exception_detail(exc: BaseException) -> str:
        parts = [f"{exc.__class__.__name__}: {repr(exc)}"]
        request = getattr(exc, "request", None)
        if request is not None:
            method = getattr(request, "method", "")
            url = getattr(request, "url", "")
            if method or url:
                parts.append(f"request={method} {url}".strip())
        if exc.__cause__ is not None:
            parts.append(f"cause={exception_detail(exc.__cause__)}")
        elif exc.__context__ is not None:
            parts.append(f"context={exception_detail(exc.__context__)}")
        return "；".join(parts)

    if isinstance(error, BaseException):
        return str(error).strip() or exception_detail(error)
    return str(error or "").strip()


async def run_platform_monitor(db: Session, platform_id: int) -> RelayPlatform:
    return await retry_platform_monitor(db, platform_id, _run_platform_monitor_once)


async def retry_platform_monitor(db: Session, platform_id: int, runner) -> RelayPlatform:
    last_platform: RelayPlatform | None = None
    last_error: str | None = None
    for attempt in range(1, MONITOR_MAX_ATTEMPTS + 1):
        try:
            platform = await runner(db, platform_id)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            last_error = error_text(exc)
            logger.warning(
                "platform monitor attempt failed platform_id=%s attempt=%s/%s error=%s",
                platform_id,
                attempt,
                MONITOR_MAX_ATTEMPTS,
                last_error,
                exc_info=True,
            )
        else:
            last_platform = platform
            if not platform.last_error:
                return platform
            last_error = platform.last_error
            logger.warning(
                "platform monitor attempt degraded platform_id=%s attempt=%s/%s error=%s",
                platform_id,
                attempt,
                MONITOR_MAX_ATTEMPTS,
                last_error,
            )

        if attempt < MONITOR_MAX_ATTEMPTS:
            await asyncio.sleep(MONITOR_RETRY_DELAY_SECONDS)

    if last_platform is not None:
        last_platform.last_error = f"采集尝试 {MONITOR_MAX_ATTEMPTS} 次后仍失败：{last_error or '未提供错误详情'}"
        update_platform_status(last_platform, [last_platform.last_error])
        db.add(last_platform)
        db.commit()
        db.refresh(last_platform)
        return last_platform
    raise RuntimeError(f"平台采集尝试 {MONITOR_MAX_ATTEMPTS} 次后失败：{last_error or '未提供错误详情'}")


async def _run_platform_monitor_once(db: Session, platform_id: int) -> RelayPlatform:
    platform = load_monitor_platform(db, platform_id)
    if platform.provider_type != "newapi":
        platform = await _run_platform_balance_monitor_once(db, platform_id)
        platform = await _run_platform_rate_monitor_once(db, platform_id)
        return platform

    errors: list[str] = []
    has_accounts = has_enabled_login_or_balance_accounts(platform)
    if has_accounts:
        platform = await _run_platform_balance_monitor_once(db, platform_id)
        if platform.last_error:
            errors.extend(platform.last_error.splitlines())

    platform = await _run_platform_rate_monitor_once(db, platform_id)
    if platform.last_error:
        errors.extend(platform.last_error.splitlines())

    platform = load_monitor_platform(db, platform_id)
    now = utcnow()
    if has_accounts:
        platform.balance_last_run_at = now
    platform.rate_last_run_at = now
    next_run_at = croniter(platform.balance_cron, now).get_next(type(now))
    platform.balance_next_run_at = next_run_at
    platform.rate_next_run_at = next_run_at
    update_platform_status(platform, dedupe_errors(errors))
    db.add(platform)
    db.commit()
    db.refresh(platform)
    return platform


def load_monitor_platform(db: Session, platform_id: int) -> RelayPlatform:
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
    return platform


def has_enabled_login_or_balance_accounts(platform: RelayPlatform) -> bool:
    return any(account.enabled for account in platform.account_monitors)


def dedupe_errors(errors: list[str | None]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for error in errors:
        error = error_text(error)
        if not error or error in seen:
            continue
        seen.add(error)
        deduped.append(error)
    return deduped


def configure_platform_proxies(platform: RelayPlatform) -> list[str]:
    proxy_urls = load_platform_proxy_urls(get_settings().sub2api.database, platform.base_url)
    setattr(platform, "sub2api_proxy_url", proxy_urls[0] if proxy_urls else None)
    enabled_account_index = 0
    for account in platform.account_monitors:
        if not account.enabled:
            continue
        proxy_url = (
            proxy_urls[enabled_account_index % len(proxy_urls)]
            if proxy_urls
            else None
        )
        enabled_account_index += 1
        setattr(account, "sub2api_proxy_url", proxy_url)
        account.last_proxy_url = masked_proxy_url(proxy_url)
    return proxy_urls


async def measure_platform_connect_latency_ms(platform: RelayPlatform) -> int | None:
    parts = urlsplit(platform.base_url)
    host = parts.hostname
    if not host:
        return None
    port = parts.port
    if port is None:
        port = 443 if parts.scheme == "https" else 80

    ssl_context = ssl.create_default_context() if parts.scheme == "https" else None
    started_at = monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl_context, server_hostname=host if ssl_context else None),
            timeout=CONNECT_LATENCY_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "connect latency probe failed platform_id=%s base_url=%s error=%s",
            platform.id,
            platform.base_url,
            error_text(exc),
        )
        return None

    connect_latency_ms = max(0, round((monotonic() - started_at) * 1000))
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001
        pass
    return connect_latency_ms


async def update_platform_connect_latency(platform: RelayPlatform) -> None:
    platform.connect_latency_ms = await measure_platform_connect_latency_ms(platform)


def model_test_headers(platform: RelayPlatform, api_key: str | None) -> dict[str, str]:
    if not api_key:
        return {}
    value = api_key
    prefix = (platform.auth_header_prefix or "").strip()
    if prefix and not api_key.lower().startswith(prefix.lower() + " "):
        value = f"{prefix} {api_key}"
    return {
        platform.auth_header_name or "Authorization": value,
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }


def platform_model_test_headers(platform: RelayPlatform) -> dict[str, str]:
    return model_test_headers(platform, decrypt_secret(platform.api_key_encrypted))


def credentials_api_key(credentials: object) -> str | None:
    if not isinstance(credentials, dict):
        return None
    api_key = credentials.get("api_key")
    if api_key is None:
        return None
    text = str(api_key).strip()
    return text or None


def sub2api_model_test_account_from_row(row: tuple[object, ...]) -> Sub2APIModelTestAccount | None:
    api_key = credentials_api_key(row[2] if len(row) > 2 else None)
    if not api_key:
        return None
    return Sub2APIModelTestAccount(
        account_id=int(row[0]),
        account_name=str(row[1]) if row[1] is not None else None,
        api_key=api_key,
        matched_base_url=normalize_base_url(str(row[3] or "")),
    )


def load_sub2api_model_test_account(
    platform: RelayPlatform,
) -> tuple[Sub2APIModelTestAccount | None, str | None]:
    database = get_settings().sub2api.database
    normalized_base_url = normalize_base_url(platform.base_url)
    if not normalized_base_url:
        return None, "模型测试缺少平台 base_url"
    if not database.is_configured:
        return None, "模型测试缺少 Sub2API 数据库配置"

    try:
        import psycopg
    except ImportError:
        return None, "模型测试无法读取 Sub2API 账号：psycopg is not installed"

    try:
        with psycopg.connect(
            database.postgresql_dsn(),
            connect_timeout=database.connect_timeout_seconds,
        ) as conn:
            conn.read_only = True
            with conn.cursor() as cursor:
                cursor.execute(SUB2API_MODEL_TEST_ACCOUNT_SQL, {"base_url": normalized_base_url})
                row = cursor.fetchone()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "sub2api model test account lookup failed platform_id=%s base_url=%s error=%s",
            platform.id,
            normalized_base_url,
            exc,
        )
        return None, f"模型测试无法读取 Sub2API 账号：{error_text(exc)}"

    if row is None:
        return None, "模型测试未找到匹配 base_url 且包含 API Key 的 Sub2API 账号"
    account = sub2api_model_test_account_from_row(row)
    if account is None:
        return None, "模型测试匹配到的 Sub2API 账号缺少 credentials.api_key"
    return account, None


def openai_chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def openai_chat_completions_payload(model: str) -> dict[str, object]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": MODEL_TEST_PROMPT}],
        "stream": True,
    }


def sse_data_from_line(line: str) -> str | None:
    line = line.strip()
    if not line.startswith("data:"):
        return None
    return line.removeprefix("data:").strip()


def chat_completion_chunk_has_token(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    choices = data.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("content"), str) and delta["content"]:
            return True
        message = choice.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str) and message["content"]:
            return True
    return False


async def measure_platform_model_first_token_ms(platform: RelayPlatform) -> ModelFirstTokenResult:
    model = (platform.model_test_model or "").strip()
    if not model:
        return ModelFirstTokenResult()
    account, account_error = load_sub2api_model_test_account(platform)
    if account_error:
        return ModelFirstTokenResult(error=account_error)
    headers = model_test_headers(platform, account.api_key if account else None)
    if not headers:
        return ModelFirstTokenResult(error="模型测试缺少 API Key")

    url = openai_chat_completions_url(platform.base_url)
    started_at = monotonic()
    try:
        async with httpx.AsyncClient(timeout=MODEL_TEST_TIMEOUT_SECONDS) as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                json=openai_chat_completions_payload(model),
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    text = body.decode("utf-8", errors="replace").strip()
                    return ModelFirstTokenResult(
                        error=f"模型测试 HTTP {response.status_code}: {text[:500]}",
                    )
                async for line in response.aiter_lines():
                    payload = sse_data_from_line(line)
                    if not payload:
                        continue
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, dict) and isinstance(data.get("error"), dict):
                        message = data["error"].get("message") or "模型测试返回错误"
                        return ModelFirstTokenResult(error=str(message))
                    if chat_completion_chunk_has_token(data):
                        return ModelFirstTokenResult(
                            first_token_ms=max(0, round((monotonic() - started_at) * 1000)),
                        )
    except Exception as exc:  # noqa: BLE001
        return ModelFirstTokenResult(error=error_text(exc))
    return ModelFirstTokenResult(error="模型测试未收到首 token")


async def update_platform_model_first_token(platform: RelayPlatform) -> None:
    result = await measure_platform_model_first_token_ms(platform)
    platform.model_first_token_ms = result.first_token_ms
    platform.model_test_error = result.error


def add_platform_snapshot(db: Session, platform: RelayPlatform, created_at: datetime | None = None) -> None:
    db.add(
        PlatformSnapshot(
            platform_id=platform.id,
            status=platform.status,
            balance=platform.balance,
            quota_used=platform.quota_used,
            quota_limit=platform.quota_limit,
            latency_ms=platform.latency_ms,
            connect_latency_ms=platform.connect_latency_ms,
            model_first_token_ms=platform.model_first_token_ms,
            model_test_error=platform.model_test_error,
            error_message=platform.last_error,
            created_at=created_at or platform.checked_at or utcnow(),
        )
    )


async def run_platform_balance_monitor(db: Session, platform_id: int) -> RelayPlatform:
    return await retry_platform_monitor(db, platform_id, _run_platform_balance_monitor_once)


async def _run_platform_balance_monitor_once(db: Session, platform_id: int) -> RelayPlatform:
    platform = load_monitor_platform(db, platform_id)

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

    previous_newapi_login_site_url: str | None = None
    configure_platform_proxies(platform)
    await update_platform_connect_latency(platform)
    await update_platform_model_first_token(platform)
    for account in platform.account_monitors:
        if not account.enabled:
            continue
        newapi_login_site_url = newapi_account_login_site_url(strategy, platform, account)
        if (
            previous_newapi_login_site_url is not None
            and newapi_login_site_url is not None
            and newapi_login_site_url == previous_newapi_login_site_url
        ):
            await asyncio.sleep(2.0)
        if newapi_login_site_url is not None:
            previous_newapi_login_site_url = newapi_login_site_url
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
            account.last_error = account_error_message(account, result.error)
            if result.error:
                errors.append(account.last_error or result.error)
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
            account.last_error = account_error_message(account, error_text(exc))
            errors.append(account.last_error)
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
    add_platform_snapshot(db, platform, platform.checked_at or now)
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


def newapi_account_login_site_url(
    strategy,
    platform: RelayPlatform,
    account: PlatformAccountMonitor,
) -> str | None:
    if platform.provider_type != "newapi":
        return None
    if not account.username or not account.password_encrypted:
        return None
    site_url = getattr(strategy, "site_url", None)
    if not callable(site_url):
        return platform.base_url.rstrip("/") + "/"
    return site_url(platform)


def account_error_message(account: PlatformAccountMonitor, error: str | BaseException | None) -> str | None:
    message = error_text(error)
    if not message:
        return None
    parts = [account.name]
    if account.username:
        parts.append(account.username)
    if account.external_account_id:
        parts.append(account.external_account_id)
    target = " / ".join(str(part) for part in parts if part)
    if target:
        return f"账号监控失败（{target}）：{message}"
    return f"账号监控失败（账号 #{account.id}）：{message}"


def is_optional_newapi_channel_privilege_error(
    strategy,
    platform: RelayPlatform,
    message: str,
) -> bool:
    if platform.provider_type != "newapi":
        return False
    checker = getattr(strategy, "is_insufficient_privileges_message", None)
    if callable(checker):
        return bool(checker(message))
    return "insufficient privileges" in message.lower()


async def run_platform_rate_monitor(db: Session, platform_id: int) -> RelayPlatform:
    return await retry_platform_monitor(db, platform_id, _run_platform_rate_monitor_once)


async def _run_platform_rate_monitor_once(db: Session, platform_id: int) -> RelayPlatform:
    platform = load_monitor_platform(db, platform_id)
    configure_platform_proxies(platform)
    await update_platform_connect_latency(platform)
    await update_platform_model_first_token(platform)

    strategy = provider_registry.get(platform.provider_type)
    errors: list[str] = []
    rate_changes: list[GroupRateChange] = []
    group_catalog_changes: list[GroupCatalogChange] = []
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
            errors.append(f"密钥绑定分组目录读取失败：{error_text(exc)}")
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
            message = error_text(exc)
            if is_optional_newapi_channel_privilege_error(strategy, platform, message):
                logger.info(
                    "rate monitor channel catalog skipped for insufficient privileges platform_id=%s name=%s error=%s",
                    platform.id,
                    platform.name,
                    exc,
                )
            else:
                errors.append(f"渠道倍率目录读取失败：{message}")
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
                errors.append(channel_error_message(item, item.error))
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
        errors.append(f"分组倍率目录读取失败：{error_text(exc)}")
        logger.exception(
            "rate monitor group catalog failed platform_id=%s name=%s",
            platform.id,
            platform.name,
        )

    if discovered_catalog is not None:
        previous_discovered_groups = current_discovered_group_catalog(db, platform.id)
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
        group_catalog_changes = group_catalog_delta(previous_discovered_groups, discovered_groups)
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
                errors.append(group_error_message(item, item.error))
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
                errors.append(group_error_message(group, result.error))
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
                error=error_text(exc),
                checked_at=checked_at,
            )
            errors.append(group_error_message(group, error_text(exc)))
            logger.exception(
                "rate monitor configured group exception platform_id=%s group_id=%s group_name=%s",
                platform.id,
                group.external_group_id,
                group.name,
            )

    now = utcnow()
    platform.rate_last_run_at = now
    platform.rate_next_run_at = croniter(platform.rate_cron, now).get_next(type(now))
    notify_group_rate_changes(db, platform, rate_changes, group_catalog_changes)
    update_platform_status(platform, errors)
    add_platform_snapshot(db, platform, platform.checked_at or now)
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


def channel_error_message(channel: DiscoveredChannelRateResult, error: str | BaseException | None) -> str:
    target = monitored_target_label(channel.name, channel.external_channel_id)
    return f"渠道倍率监控失败（{target}）：{error_text(error)}"


def group_error_message(
    group: DiscoveredGroupRateResult | PlatformGroupMonitor,
    error: str | BaseException | None,
) -> str:
    target = monitored_target_label(group.name, group.external_group_id)
    return f"分组倍率监控失败（{target}）：{error_text(error)}"


def monitored_target_label(name: str | None, external_id: str | None) -> str:
    parts = [str(part) for part in (name, external_id) if part]
    return " / ".join(parts) if parts else "未知目标"


def current_discovered_group_catalog(
    db: Session,
    platform_id: int,
) -> dict[str, GroupCatalogItem]:
    rows = db.scalars(
        select(PlatformDiscoveredGroupRate).where(
            PlatformDiscoveredGroupRate.platform_id == platform_id,
        )
    ).all()
    return {
        row.external_group_id: GroupCatalogItem(
            external_group_id=row.external_group_id,
            name=row.name,
            rate_multiplier=row.rate_multiplier,
            rpm_limit=row.rpm_limit,
        )
        for row in rows
    }


def group_catalog_delta(
    previous_groups: dict[str, GroupCatalogItem],
    current_groups: dict[str, DiscoveredGroupRateResult],
) -> list[GroupCatalogChange]:
    if not previous_groups:
        return []

    changes: list[GroupCatalogChange] = []
    for external_group_id in sorted(set(current_groups) - set(previous_groups)):
        item = current_groups[external_group_id]
        changes.append(
            GroupCatalogChange(
                action="added",
                group_name=item.name,
                external_group_id=item.external_group_id,
                rate_multiplier=item.rate_multiplier,
                rpm_limit=item.rpm_limit,
            )
        )
    for external_group_id in sorted(set(previous_groups) - set(current_groups)):
        item = previous_groups[external_group_id]
        changes.append(
            GroupCatalogChange(
                action="removed",
                group_name=item.name,
                external_group_id=item.external_group_id,
                rate_multiplier=item.rate_multiplier,
                rpm_limit=item.rpm_limit,
            )
        )
    return changes


def update_platform_status(platform: RelayPlatform, errors: list[str | None]) -> None:
    errors = dedupe_errors(errors)
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
        logger.debug(
            "key group monitor sync skipped platform_id=%s name=%s source=%s candidates=0",
            platform.id,
            platform.name,
            "catalog" if key_groups is not None else "account_key_summaries",
        )
        return

    existing_groups = {group.external_group_id: group for group in platform.group_monitors}
    source = "catalog" if key_groups is not None else "account_key_summaries"
    changed = False
    added_count = 0
    renamed_count = 0
    unchanged_count = 0
    for external_group_id, name in candidates.items():
        existing_group = existing_groups.get(external_group_id)
        if existing_group is not None:
            default_names = {external_group_id, f"分组 {external_group_id}"}
            if existing_group.name in default_names and existing_group.name != name:
                existing_group.name = name
                db.add(existing_group)
                changed = True
                renamed_count += 1
                logger.info(
                    "key group monitor sync renamed default group platform_id=%s group_db_id=%s external_group_id=%s name=%s source=%s",
                    platform.id,
                    existing_group.id,
                    external_group_id,
                    name,
                    source,
                )
            else:
                unchanged_count += 1
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
        added_count += 1
        logger.info(
            "key group monitor sync added group platform_id=%s external_group_id=%s name=%s source=%s",
            platform.id,
            external_group_id,
            name,
            source,
        )

    if changed:
        db.flush()
    logger.info(
        "key group monitor sync done platform_id=%s name=%s source=%s candidates=%s added=%s renamed=%s unchanged=%s changed=%s",
        platform.id,
        platform.name,
        source,
        len(candidates),
        added_count,
        renamed_count,
        unchanged_count,
        changed,
    )


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
