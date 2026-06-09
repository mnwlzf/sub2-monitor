import asyncio
import logging
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from http.cookies import SimpleCookie
from time import monotonic
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.security import decrypt_secret
from app.models.monitor import PlatformAccountMonitor, PlatformGroupMonitor
from app.models.platform import RelayPlatform

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountBalanceResult:
    balance: float | None = None
    quota_used: float | None = None
    quota_limit: float | None = None
    key_summaries: tuple[dict[str, str | None], ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class GroupRateResult:
    rate_multiplier: float | None = None
    rpm_limit: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class DiscoveredGroupRateResult:
    external_group_id: str
    name: str
    description: str | None = None
    rate_multiplier: float | None = None
    rpm_limit: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class DiscoveredChannelRateResult:
    external_channel_id: str
    name: str
    description: str | None = None
    base_url: str | None = None
    status: str | None = None
    rate_multiplier: float | None = None
    model_rates: dict[str, float] | None = None
    error: str | None = None


@dataclass(frozen=True)
class KeyGroupMonitorResult:
    external_group_id: str
    name: str


class ProviderStrategy(ABC):
    provider_type: str
    label: str
    description: str

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    async def fetch_account_balance(
        self,
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        """Fetch one account's balance/quota state from a provider platform."""

    @abstractmethod
    async def fetch_group_rate(
        self,
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        """Fetch one group's rate multiplier state from a provider platform."""

    async def fetch_group_catalog(
        self,
        platform: RelayPlatform,
    ) -> list[DiscoveredGroupRateResult] | None:
        """Fetch all discoverable groups from a provider platform if supported."""
        return None

    async def fetch_channel_catalog(
        self,
        platform: RelayPlatform,
    ) -> list[DiscoveredChannelRateResult] | None:
        """Fetch all discoverable channel rates from a provider platform if supported."""
        return None

    async def fetch_key_group_catalog(
        self,
        platform: RelayPlatform,
    ) -> list[KeyGroupMonitorResult] | None:
        """Fetch groups currently bound to user API keys if supported."""
        return None

    def auth_headers(self, platform: RelayPlatform) -> dict[str, str]:
        api_key = decrypt_secret(platform.api_key_encrypted)
        if not api_key:
            return {}
        value = api_key
        prefix = platform.auth_header_prefix.strip()
        if prefix:
            value = f"{prefix} {api_key}"
        return {platform.auth_header_name: value}

    async def get_json(self, platform: RelayPlatform, path: str) -> tuple[int, Any, int]:
        base_url = platform.base_url.rstrip("/")
        url = f"{base_url}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(url, headers=self.auth_headers(platform))
        try:
            latency_ms = int(response.elapsed.total_seconds() * 1000)
        except Exception:  # noqa: BLE001
            latency_ms = 0
        if not response.headers.get("content-type", "").lower().startswith("application/json"):
            return response.status_code, {}, latency_ms
        return response.status_code, response.json(), latency_ms

    @staticmethod
    def first_number(payload: Any, keys: tuple[str, ...]) -> float | None:
        if not isinstance(payload, dict):
            return None
        candidates = [payload]
        for nested_key in ("data", "result", "stats", "user", "account", "group"):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                candidates.append(nested)
        for item in candidates:
            for key in keys:
                value = item.get(key)
                if isinstance(value, int | float):
                    return float(value)
                if isinstance(value, str):
                    try:
                        return float(value)
                    except ValueError:
                        pass
        return None


class NewApiSiteStrategy(ABC):
    site_strategy: str
    label: str
    description: str

    @abstractmethod
    async def fetch_account_balance(
        self,
        provider: "NewApiStrategy",
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        """Fetch an account balance for one New API site variant."""

    @abstractmethod
    async def fetch_group_rate(
        self,
        provider: "NewApiStrategy",
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        """Fetch a group rate for one New API site variant."""

    async def fetch_group_catalog(
        self,
        provider: "NewApiStrategy",
        platform: RelayPlatform,
    ) -> list[DiscoveredGroupRateResult] | None:
        """Fetch all discoverable groups for a New API site variant if supported."""
        return None


class GenericNewApiSiteStrategy(NewApiSiteStrategy):
    DEFAULT_QUOTA_PER_UNIT = 500_000
    LOGIN_RATE_LIMIT_RETRY_DELAYS = (5.0, 15.0, 30.0, 60.0)
    ACCOUNT_LOGIN_SPACING_SECONDS = 2.0
    LOGIN_RETRY_JITTER_SECONDS = 2.0
    LOGIN_ENDPOINTS = ("api/user/login?turnstile=", "api/user/login")
    PRICING_ENDPOINTS = ("api/pricing", "pricing")
    GROUPS_ENDPOINT = "api/user/self/groups"

    site_strategy = "generic"
    label = "通用 New API"
    description = "通用 New API 策略：登录后读取 /api/user/self、/api/user/self/groups 和渠道倍率接口"

    async def fetch_account_balance(
        self,
        provider: "NewApiStrategy",
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        platform_id = getattr(platform, "id", None)
        platform_name = getattr(platform, "name", None)
        account_id = getattr(account, "id", None)
        account_name = getattr(account, "name", None)
        external_account_id = getattr(account, "external_account_id", None)
        logger.debug(
            "newapi balance start platform_id=%s platform_name=%s account_id=%s account_name=%s external_account_id=%s",
            platform_id,
            platform_name,
            account_id,
            account_name,
            external_account_id,
        )
        if not account.username or not account.password_encrypted:
            status, payload, _ = await provider.get_json(
                platform,
                f"/api/account/{account.external_account_id}",
            )
            if status >= 400:
                return AccountBalanceResult(error=f"newapi account endpoint returned HTTP {status}")
            return AccountBalanceResult(
                balance=provider.first_number(payload, ("balance", "remaining_quota", "remain_quota")),
                quota_used=provider.first_number(payload, ("used_quota", "quota_used", "used")),
                quota_limit=provider.first_number(payload, ("quota", "total_quota", "quota_limit")),
            )

        password = decrypt_secret(account.password_encrypted)
        if not password:
            return AccountBalanceResult(error="newapi account balance password decrypt failed or empty")

        site_url = self.site_url(platform)
        request_headers = {
            "Accept": "application/json, text/plain, */*",
            "Cache-Control": "no-store",
            "Origin": self.site_origin(platform),
            "Referer": f"{site_url}login",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
        }
        async with httpx.AsyncClient(
            base_url=site_url,
            follow_redirects=True,
            headers=request_headers,
            timeout=provider.timeout_seconds,
        ) as client:
            quota_per_unit = await self.fetch_quota_per_unit(provider, client)
            auth_headers = await self.login_headers_for_account(provider, platform, account, client)
            if auth_headers is None:
                return AccountBalanceResult(error="newapi login failed")
            self_response = await client.get(
                "api/user/self",
                headers=auth_headers,
            )
            authorization_header = auth_headers.get("Authorization")
            access_token = authorization_header
            if access_token and access_token.lower().startswith("bearer "):
                access_token = access_token[7:].strip()
            cookie_header = auth_headers.get("Cookie")
            user_id = auth_headers["New-Api-User"]
            if (
                authorization_header
                and self_response.status_code in {401, 403}
                and self.looks_like_invalid_token(self_response)
            ):
                retry_headers = {"Authorization": access_token, "New-Api-User": str(user_id)}
                if cookie_header:
                    retry_headers["Cookie"] = cookie_header
                logger.warning(
                    "newapi self rejected bearer token, retrying raw token platform_id=%s account_id=%s status=%s",
                    platform_id,
                    account_id,
                    self_response.status_code,
                )
                self_response = await client.get(
                    "api/user/self",
                    headers=retry_headers,
                )
                if self_response.status_code < 400:
                    auth_headers = retry_headers
                    provider.cache_login_headers(site_url, account, auth_headers)
            if (
                access_token
                and self_response.status_code in {401, 403}
                and self.looks_like_invalid_token(self_response)
            ):
                retry_headers = {"New-Api-User": str(user_id)}
                if cookie_header:
                    retry_headers["Cookie"] = cookie_header
                logger.warning(
                    "newapi self rejected login token, retrying session cookie platform_id=%s account_id=%s status=%s",
                    platform_id,
                    account_id,
                    self_response.status_code,
                )
                self_response = await client.get(
                    "api/user/self",
                    headers=retry_headers,
                )
                if self_response.status_code < 400:
                    auth_headers = retry_headers
                    provider.cache_login_headers(site_url, account, auth_headers)
            if self_response.status_code >= 400:
                if self_response.status_code in {401, 403}:
                    provider.drop_cached_login_headers(site_url, account)
                logger.warning(
                    "newapi self failed platform_id=%s account_id=%s status=%s",
                    platform_id,
                    account_id,
                    self_response.status_code,
                )
                return AccountBalanceResult(
                    error=f"newapi self endpoint returned HTTP {self_response.status_code}"
                )
            payload = self.safe_json(self_response)
            key_summaries: tuple[dict[str, str | None], ...] = ()
            key_summary_error: str | None = None
            try:
                fetched_key_summaries = await provider.fetch_token_summaries(
                    client,
                    request_headers=auth_headers,
                    string_group_as_id=True,
                )
                if fetched_key_summaries:
                    key_summaries = fetched_key_summaries
                    logger.debug(
                        "newapi token summaries fetched platform_id=%s account_id=%s keys=%s",
                        platform_id,
                        account_id,
                        len(key_summaries),
                    )
            except Exception as exc:  # noqa: BLE001
                key_summary_error = str(exc)
                logger.warning(
                    "newapi token summaries failed platform_id=%s account_id=%s error=%s",
                    platform_id,
                    account_id,
                    key_summary_error,
                )

        quota = provider.first_number(payload, ("quota",))
        if quota is None:
            logger.warning(
                "newapi self missing quota platform_id=%s account_id=%s payload=%s",
                platform_id,
                account_id,
                payload,
            )
            return AccountBalanceResult(error="newapi self response missing numeric data.quota")
        used_quota = provider.first_number(payload, ("used_quota",))
        logger.debug(
            "newapi balance done platform_id=%s account_id=%s balance=%s used_quota=%s quota_per_unit=%s",
            platform_id,
            account_id,
            quota / quota_per_unit,
            used_quota / quota_per_unit if used_quota is not None else None,
            quota_per_unit,
        )
        return AccountBalanceResult(
            balance=quota / quota_per_unit,
            quota_used=used_quota / quota_per_unit if used_quota is not None else None,
            key_summaries=key_summaries,
            error=key_summary_error,
        )

    async def fetch_group_rate(
        self,
        provider: "NewApiStrategy",
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        platform_id = getattr(platform, "id", None)
        platform_name = getattr(platform, "name", None)
        group_id = getattr(group, "id", None)
        group_name = getattr(group, "name", None)
        external_group_id = getattr(group, "external_group_id", None)
        logger.debug(
            "newapi group rate start platform_id=%s platform_name=%s group_id=%s group_name=%s external_group_id=%s",
            platform_id,
            platform_name,
            group_id,
            group_name,
            external_group_id,
        )
        headers = await provider.resolve_management_headers(platform)
        logger.debug(
            "newapi group rate auth resolved platform_id=%s group_id=%s auth=%s",
            platform_id,
            group_id,
            provider.auth_debug_summary(headers),
        )
        if "New-Api-User" not in headers:
            return GroupRateResult(
                error=(
                    "NewAPI 分组倍率读取失败：缺少 New-Api-User。"
                    "请在平台配置中填写管理用户 ID，或配置一个启用的登录账号。"
                )
            )
        async with httpx.AsyncClient(
            base_url=self.site_url(platform),
            headers=headers,
            timeout=provider.timeout_seconds,
        ) as client:
            response, pricing_endpoint = await self.get_first_available(
                client,
                self.PRICING_ENDPOINTS,
        )
        if response.status_code >= 400:
            payload = self.safe_json(response)
            logger.warning(
                "newapi pricing failed platform_id=%s group_id=%s group_name=%s target=%s status=%s endpoint=%s summary=%s",
                platform_id,
                group_id,
                group_name,
                external_group_id,
                response.status_code,
                pricing_endpoint,
                self.response_debug_summary(response, payload),
            )
            return GroupRateResult(
                error=(
                    "NewAPI 分组倍率读取失败："
                    f"{pricing_endpoint} 返回 HTTP {response.status_code}。"
                    "请检查管理凭证是否有效，或上游站点是否开放 pricing 接口。"
                )
            )
        payload = self.safe_json(response)
        if not isinstance(payload, dict) or not isinstance(payload.get("group_ratio"), dict):
            logger.warning(
                "newapi pricing missing group_ratio platform_id=%s group_id=%s group_name=%s endpoint=%s summary=%s",
                platform_id,
                group_id,
                group_name,
                pricing_endpoint,
                self.response_debug_summary(response, payload),
            )
            return GroupRateResult(
                error=(
                    "NewAPI 分组倍率读取失败：pricing 响应缺少 group_ratio。"
                    "请确认该站点是 NewAPI 兼容接口，并且当前账号有权限访问 pricing。"
                )
            )
        raw_rate = payload["group_ratio"].get(group.external_group_id)
        if raw_rate is None:
            available_groups = list(payload["group_ratio"])[:8]
            logger.warning(
                "newapi pricing missing group ratio platform_id=%s group_id=%s group_name=%s target=%s available_count=%s available_sample=%s",
                platform_id,
                group_id,
                group_name,
                external_group_id,
                len(payload["group_ratio"]),
                available_groups,
            )
            return GroupRateResult(
                error=(
                    f"NewAPI pricing 中没有找到分组 {external_group_id!r}。"
                    "请确认监控分组 ID 与上游实际分组 ID 完全一致；"
                    f"当前可用分组示例：{', '.join(str(item) for item in available_groups) or '无'}。"
                )
            )
        try:
            return GroupRateResult(rate_multiplier=float(raw_rate))
        except (TypeError, ValueError):
            return GroupRateResult(
                error=f"NewAPI 分组倍率格式错误：分组 {external_group_id!r} 的倍率不是数字：{raw_rate!r}"
            )

    async def fetch_group_catalog(
        self,
        provider: "NewApiStrategy",
        platform: RelayPlatform,
    ) -> list[DiscoveredGroupRateResult] | None:
        platform_id = getattr(platform, "id", None)
        platform_name = getattr(platform, "name", None)
        auth_headers = await provider.resolve_management_headers(platform)
        logger.debug(
            "newapi group catalog start platform_id=%s platform_name=%s auth=%s endpoint=%s",
            platform_id,
            platform_name,
            provider.auth_debug_summary(auth_headers),
            self.GROUPS_ENDPOINT,
        )
        errors: list[str] = []
        try:
            return await self.fetch_group_catalog_with_headers(provider, platform, auth_headers)
        except ValueError as exc:
            errors.append(str(exc))
            logger.warning(
                "newapi group catalog attempt failed platform_id=%s platform_name=%s auth=%s error=%s",
                platform_id,
                platform_name,
                provider.auth_debug_summary(auth_headers),
                exc,
            )

        fallback_candidates: list[dict[str, str]] = []

        def add_fallback_candidate(headers: dict[str, str] | None) -> None:
            if not headers:
                return
            candidate = dict(headers)
            if candidate == auth_headers:
                return
            if candidate in fallback_candidates:
                return
            fallback_candidates.append(candidate)

        if "Authorization" in auth_headers and "Cookie" in auth_headers:
            cookie_only_headers = dict(auth_headers)
            cookie_only_headers.pop("Authorization", None)
            add_fallback_candidate(cookie_only_headers)

        for headers in fallback_candidates:
            try:
                return await self.fetch_group_catalog_with_headers(provider, platform, headers)
            except ValueError as exc:
                errors.append(str(exc))
                logger.warning(
                    "newapi group catalog fallback failed platform_id=%s platform_name=%s auth=%s error=%s",
                    platform_id,
                    platform_name,
                    provider.auth_debug_summary(headers),
                    exc,
                )

        fallback_candidates = []
        add_fallback_candidate(await provider.login_management_headers(platform, force_refresh=True))
        for candidate in await provider.login_management_header_candidates(platform):
            add_fallback_candidate(candidate)

        for headers in fallback_candidates:
            try:
                return await self.fetch_group_catalog_with_headers(provider, platform, headers)
            except ValueError as exc:
                errors.append(str(exc))
                logger.warning(
                    "newapi group catalog login fallback failed platform_id=%s platform_name=%s auth=%s error=%s",
                    platform_id,
                    platform_name,
                    provider.auth_debug_summary(headers),
                    exc,
                )

        if errors:
            raise ValueError(errors[-1])
        return None

    async def fetch_group_catalog_with_headers(
        self,
        provider: "NewApiStrategy",
        platform: RelayPlatform,
        headers: dict[str, str],
    ) -> list[DiscoveredGroupRateResult] | None:
        platform_id = getattr(platform, "id", None)
        platform_name = getattr(platform, "name", None)
        site_url = self.site_url(platform)
        async with httpx.AsyncClient(
            base_url=site_url,
            follow_redirects=True,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Cache-Control": "no-store",
                "Origin": self.site_origin(platform),
                "Referer": f"{site_url}login",
                **headers,
            },
            timeout=provider.timeout_seconds,
        ) as client:
            response = await client.get(self.GROUPS_ENDPOINT)
            payload = self.safe_json(response)
            logger.debug(
                "newapi group catalog response platform_id=%s platform_name=%s auth=%s summary=%s",
                platform_id,
                platform_name,
                provider.auth_debug_summary(headers),
                self.response_debug_summary(response, payload),
            )
            if response.status_code >= 400:
                message = self.response_message(payload)
                suffix = f"上游提示：{message}" if message else self.response_debug_summary(response, payload)
                raise ValueError(
                    "NewAPI 分组目录读取失败："
                    f"{self.GROUPS_ENDPOINT} 返回 HTTP {response.status_code}。"
                    f"{suffix}。请检查管理凭证是否有效，或该账号是否有权限读取用户分组。"
                )
            if self.response_failed(payload):
                message = self.response_message(payload)
                if message:
                    raise ValueError(f"NewAPI 分组目录读取失败：上游返回失败，提示：{message}")
                raise ValueError(
                    "NewAPI 分组目录读取失败：上游返回失败，但没有提供明确提示。"
                    f"{self.response_debug_summary(response, payload)}。"
                )

        groups = self.parse_group_catalog_payload(payload)
        if groups is None:
            raise ValueError(
                "NewAPI 分组目录读取失败：响应缺少 data 分组对象。"
                "newapi group catalog response missing data "
                f"({self.response_debug_summary(response, payload)})。"
                "常见原因：管理凭证失效、请求被重定向到登录页，或上游站点接口格式不是 NewAPI。"
            )
        logger.info(
            "newapi group catalog fetched platform_id=%s platform_name=%s groups=%s auth=%s",
            platform_id,
            platform_name,
            len(groups),
            provider.auth_debug_summary(headers),
        )
        return groups

    async def login_headers_for_account(
        self,
        provider: "NewApiStrategy",
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
        client: httpx.AsyncClient,
    ) -> dict[str, str] | None:
        cached_headers = provider.cached_login_headers(self.site_url(platform), account)
        if cached_headers is not None:
            return cached_headers

        password = decrypt_secret(account.password_encrypted)
        if not password:
            return None

        await client.get("login")
        login_response, _ = await self.post_login_with_rate_limit_retry(
            client,
            self.LOGIN_ENDPOINTS,
            json={
                "username": account.username,
                "password": password,
            },
        )
        if login_response.status_code >= 400:
            return None
        login_payload_json = self.safe_json(login_response)
        if isinstance(login_payload_json, dict) and login_payload_json.get("success") is False:
            return None

        user_id = self.extract_user_id(login_payload_json)
        if user_id is None:
            return None

        auth_headers: dict[str, str] = {"New-Api-User": str(user_id)}
        access_token = self.extract_access_token(login_payload_json)
        if access_token:
            auth_headers["Authorization"] = f"Bearer {access_token}"
        cookie_header = self.session_cookie_header(login_response, client)
        if cookie_header:
            auth_headers["Cookie"] = cookie_header
        provider.cache_login_headers(self.site_url(platform), account, auth_headers)
        return auth_headers

    @staticmethod
    def parse_group_catalog_payload(payload: Any) -> list[DiscoveredGroupRateResult] | None:
        if not isinstance(payload, dict):
            return None
        data = GenericNewApiSiteStrategy.group_catalog_data(payload)
        if data is None:
            return None

        groups: list[DiscoveredGroupRateResult] = []
        for external_group_id, raw_group in GenericNewApiSiteStrategy.group_catalog_items(data):
            group = GenericNewApiSiteStrategy.parse_group_catalog_item(external_group_id, raw_group)
            if group is not None:
                groups.append(group)
        return groups

    @staticmethod
    def group_catalog_data(payload: dict[str, Any]) -> Any | None:
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("groups", "items", "list", "records", "group_ratio"):
                candidate = data.get(key)
                if isinstance(candidate, dict | list):
                    return candidate
        for candidate in (data, payload.get("groups"), payload.get("group_ratio")):
            if isinstance(candidate, dict | list):
                return candidate
        return None

    @staticmethod
    def group_catalog_items(data: Any) -> list[tuple[Any, Any]]:
        if isinstance(data, dict):
            return list(data.items())
        if isinstance(data, list):
            items: list[tuple[Any, Any]] = []
            for index, item in enumerate(data):
                if isinstance(item, dict):
                    external_group_id = (
                        item.get("id")
                        or item.get("group")
                        or item.get("group_id")
                        or item.get("name")
                        or item.get("key")
                    )
                    items.append((external_group_id or index, item))
                else:
                    items.append((item, item))
            return items
        return []

    @staticmethod
    def parse_group_catalog_item(external_group_id: Any, raw_group: Any) -> DiscoveredGroupRateResult | None:
        if not isinstance(external_group_id, str | int | float):
            return None
        name = str(external_group_id).strip()
        if not name:
            return None

        description: str | None = None
        rate_multiplier: float | None = None
        rpm_limit: int | None = None
        error: str | None = None

        if isinstance(raw_group, dict):
            raw_name = raw_group.get("name") or raw_group.get("group_name") or raw_group.get("label")
            if isinstance(raw_name, str) and raw_name.strip():
                name = raw_name.strip()
            desc = raw_group.get("desc") or raw_group.get("description")
            if isinstance(desc, str) and desc.strip():
                description = desc.strip()
            raw_ratio = raw_group.get("ratio", raw_group.get("rate_multiplier", raw_group.get("rate")))
            if raw_ratio is not None:
                try:
                    rate_multiplier = float(raw_ratio)
                except (TypeError, ValueError):
                    error = f"newapi group ratio is not numeric: {raw_ratio!r}"
            raw_rpm = raw_group.get("rpm_limit", raw_group.get("rpm"))
            if raw_rpm is not None:
                try:
                    rpm_limit = int(float(raw_rpm))
                except (TypeError, ValueError):
                    if error is None:
                        error = f"newapi group rpm is not numeric: {raw_rpm!r}"
        elif isinstance(raw_group, int | float | str):
            try:
                rate_multiplier = float(raw_group)
            except (TypeError, ValueError):
                if str(raw_group).strip() and str(raw_group).strip() != name:
                    description = str(raw_group).strip()
        else:
            error = f"newapi group payload is not an object: {raw_group!r}"

        return DiscoveredGroupRateResult(
            external_group_id=str(external_group_id).strip(),
            name=name,
            description=description,
            rate_multiplier=rate_multiplier,
            rpm_limit=rpm_limit,
            error=error,
        )

    @staticmethod
    def site_url(platform: RelayPlatform) -> str:
        return NewApiStrategy.site_url(platform)

    @staticmethod
    def site_origin(platform: RelayPlatform) -> str:
        return NewApiStrategy.site_origin(platform)

    @staticmethod
    def site_base_path(path: str) -> str:
        return NewApiStrategy.site_base_path(path)

    @staticmethod
    def safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {}

    @staticmethod
    def response_failed(payload: Any) -> bool:
        return NewApiStrategy.response_failed(payload)

    @staticmethod
    def response_message(payload: Any) -> str | None:
        return NewApiStrategy.response_message(payload)

    @staticmethod
    def response_debug_summary(response: httpx.Response, payload: Any) -> str:
        return NewApiStrategy.response_debug_summary(response, payload)

    async def fetch_quota_per_unit(
        self,
        provider: "NewApiStrategy",
        client: httpx.AsyncClient,
    ) -> float:
        try:
            response = await client.get("api/status")
        except httpx.HTTPError:
            return self.DEFAULT_QUOTA_PER_UNIT
        if response.status_code >= 400:
            return self.DEFAULT_QUOTA_PER_UNIT
        quota_per_unit = provider.first_number(self.safe_json(response), ("quota_per_unit",))
        if quota_per_unit is None or quota_per_unit <= 0:
            return self.DEFAULT_QUOTA_PER_UNIT
        return quota_per_unit

    @staticmethod
    def extract_user_id(payload: Any) -> int | str | None:
        return NewApiStrategy.extract_user_id(payload)

    @staticmethod
    def extract_access_token(payload: Any) -> str | None:
        return NewApiStrategy.extract_access_token(payload)

    @staticmethod
    def looks_like_invalid_token(response: httpx.Response) -> bool:
        return NewApiStrategy.looks_like_invalid_token(response)

    @staticmethod
    def session_cookie_header(response: httpx.Response, client: httpx.AsyncClient) -> str | None:
        return NewApiStrategy.session_cookie_header(response, client)

    @staticmethod
    async def get_first_available(
        client: httpx.AsyncClient,
        endpoints: tuple[str, ...],
    ) -> tuple[httpx.Response, str]:
        return await NewApiStrategy.get_first_available(client, endpoints)

    @staticmethod
    async def post_first_available(
        client: httpx.AsyncClient,
        endpoints: tuple[str, ...],
        retry_statuses: set[int] | frozenset[int] | tuple[int, ...] = (404,),
        **kwargs: Any,
    ) -> tuple[httpx.Response, str]:
        return await NewApiStrategy.post_first_available(
            client,
            endpoints,
            retry_statuses=retry_statuses,
            **kwargs,
        )

    async def post_login_with_rate_limit_retry(
        self,
        client: httpx.AsyncClient,
        endpoints: tuple[str, ...],
        **kwargs: Any,
    ) -> tuple[httpx.Response, str]:
        response, endpoint = await self.post_first_available(
            client,
            endpoints,
            retry_statuses={404},
            **kwargs,
        )
        for default_delay in self.LOGIN_RATE_LIMIT_RETRY_DELAYS:
            if response.status_code != 429:
                return response, endpoint
            delay = self.retry_after_seconds(response) or self.retry_delay_with_jitter(default_delay)
            await asyncio.sleep(delay)
            response, endpoint = await self.post_first_available(
                client,
                endpoints,
                retry_statuses={404},
                **kwargs,
            )
        return response, endpoint

    @staticmethod
    def retry_after_seconds(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            seconds = float(value)
        except ValueError:
            return None
        if seconds < 0:
            return None
        return min(seconds, 30.0)

    def retry_delay_with_jitter(self, default_delay: float) -> float:
        jitter = random.uniform(0.0, self.LOGIN_RETRY_JITTER_SECONDS)
        return default_delay + jitter


class NewApiSiteStrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, NewApiSiteStrategy] = {}
        self._aliases = {"yunjin": "generic"}

    def register(self, strategy: NewApiSiteStrategy) -> None:
        self._strategies[strategy.site_strategy] = strategy

    def get(self, site_strategy: str) -> NewApiSiteStrategy:
        site_strategy = self._aliases.get(site_strategy, site_strategy)
        if site_strategy not in self._strategies:
            supported = ", ".join(sorted(self._strategies))
            raise ValueError(
                f"Unsupported newapi site strategy {site_strategy!r}; supported: {supported}"
            )
        return self._strategies[site_strategy]

    def options(self) -> list[dict[str, str]]:
        return [
            {
                "value": strategy.site_strategy,
                "label": strategy.label,
                "provider_type": "newapi",
                "description": strategy.description,
            }
            for strategy in self._strategies.values()
        ]


class Sub2ApiStrategy(ProviderStrategy):
    provider_type = "sub2api"
    label = "Sub2API"
    description = "通过用户邮箱密码登录 Sub2API，读取余额、总消耗和可用分组倍率"

    FRONTEND_PAGE_SUFFIXES = {
        "login",
        "register",
        "dashboard",
        "keys",
        "usage",
        "profile",
        "purchase",
    }

    async def fetch_account_balance(
        self,
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        email = self.account_email(account)
        if not email:
            return AccountBalanceResult(error="Sub2API 账号余额监控需要配置登录邮箱")

        password = decrypt_secret(account.password_encrypted)
        if not password:
            return AccountBalanceResult(error="Sub2API 账号余额监控需要配置登录密码")

        async with self.api_client(platform) as client:
            login_payload, login_error = await self.login(client, email, password)
            if login_error:
                return AccountBalanceResult(error=login_error)

            user_payload = login_payload.get("user") if isinstance(login_payload, dict) else None
            if not isinstance(user_payload, dict):
                user_payload, user_error = await self.get_sub2api_data(client, "auth/me")
                if user_error:
                    return AccountBalanceResult(error=user_error)

            dashboard_payload, dashboard_error = await self.get_sub2api_data(
                client,
                "usage/dashboard/stats",
            )
            keys_payload, _ = await self.get_sub2api_data(client, "keys?page=1&page_size=100")

        balance = self.first_number(user_payload, ("balance",))
        total_recharged = self.first_number(user_payload, ("total_recharged",))
        quota_used = self.first_number(
            dashboard_payload,
            ("total_actual_cost", "actual_cost", "total_cost"),
        )
        key_quota_used, key_quota_limit = self.sum_api_key_quotas(keys_payload)
        key_summaries = self.api_key_summaries(keys_payload)
        if quota_used is None:
            quota_used = key_quota_used
        quota_limit = total_recharged if total_recharged is not None else key_quota_limit

        if dashboard_error and quota_used is None:
            return AccountBalanceResult(
                balance=balance,
                quota_limit=quota_limit,
                key_summaries=key_summaries,
                error=dashboard_error,
            )

        return AccountBalanceResult(
            balance=balance,
            quota_used=quota_used,
            quota_limit=quota_limit,
            key_summaries=key_summaries,
        )

    async def fetch_group_rate(
        self,
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        catalog = await self.fetch_group_catalog(platform)
        target = group.external_group_id.strip()
        for item in catalog or []:
            if item.external_group_id == target or item.name == target:
                return GroupRateResult(
                    rate_multiplier=item.rate_multiplier,
                    rpm_limit=item.rpm_limit,
                    error=item.error,
                )
        return GroupRateResult(error=f"Sub2API 可用分组中未找到 {group.external_group_id!r}")

    async def fetch_group_catalog(
        self,
        platform: RelayPlatform,
    ) -> list[DiscoveredGroupRateResult] | None:
        account = self.first_login_account(platform)
        if account is None:
            raise ValueError("Sub2API 分组采集需要至少配置一个启用账号，并填写邮箱和密码")

        email = self.account_email(account)
        password = decrypt_secret(account.password_encrypted)
        if not email or not password:
            raise ValueError("Sub2API 分组采集账号缺少登录邮箱或密码")

        async with self.api_client(platform) as client:
            _, login_error = await self.login(client, email, password)
            if login_error:
                raise ValueError(login_error)

            groups_payload, groups_error = await self.get_sub2api_data(client, "groups/available")
            if groups_error:
                raise ValueError(groups_error)
            rates_payload, rates_error = await self.get_sub2api_data(client, "groups/rates")
            if rates_error:
                raise ValueError(rates_error)

        return self.parse_group_catalog_payload(groups_payload, rates_payload)

    async def fetch_key_group_catalog(
        self,
        platform: RelayPlatform,
    ) -> list[KeyGroupMonitorResult] | None:
        account = self.first_login_account(platform)
        if account is None:
            return None

        email = self.account_email(account)
        password = decrypt_secret(account.password_encrypted)
        if not email or not password:
            return None

        async with self.api_client(platform) as client:
            _, login_error = await self.login(client, email, password)
            if login_error:
                raise ValueError(login_error)

            keys_payload, keys_error = await self.get_sub2api_data(
                client,
                "keys?page=1&page_size=100",
            )
            if keys_error:
                raise ValueError(keys_error)

        return self.parse_key_group_catalog(keys_payload)

    def api_client(self, platform: RelayPlatform) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{self.api_base_url(platform)}/",
            follow_redirects=True,
            headers={"Accept": "application/json"},
            timeout=self.timeout_seconds,
        )

    async def login(
        self,
        client: httpx.AsyncClient,
        email: str,
        password: str,
    ) -> tuple[dict[str, Any], str | None]:
        response = await client.post(
            "auth/login",
            json={
                "email": email,
                "password": password,
            },
        )
        payload = self.safe_json(response)
        data, api_error = self.unwrap_sub2api_response(payload)
        if response.status_code >= 400:
            return {}, f"Sub2API 登录接口返回 HTTP {response.status_code}: {api_error or ''}".strip()
        if api_error:
            return {}, f"Sub2API 登录失败: {api_error}"
        if not isinstance(data, dict):
            return {}, "Sub2API 登录响应缺少 data"
        if data.get("requires_2fa") is True:
            return {}, "Sub2API 账号启用了 TOTP 2FA，当前监控不支持二次验证码"

        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            return {}, "Sub2API 登录响应缺少 access_token"
        client.headers["Authorization"] = f"Bearer {access_token.strip()}"
        return data, None

    async def get_sub2api_data(
        self,
        client: httpx.AsyncClient,
        path: str,
    ) -> tuple[Any, str | None]:
        response = await client.get(path)
        payload = self.safe_json(response)
        data, api_error = self.unwrap_sub2api_response(payload)
        if response.status_code >= 400:
            return None, f"Sub2API {path} 返回 HTTP {response.status_code}: {api_error or ''}".strip()
        if api_error:
            return None, f"Sub2API {path} 返回错误: {api_error}"
        return data, None

    @classmethod
    def api_base_url(cls, platform: RelayPlatform) -> str:
        raw = platform.base_url.strip().rstrip("/")
        parts = urlsplit(raw)
        if not parts.scheme or not parts.netloc:
            if raw.endswith("/api/v1"):
                return raw
            if raw.endswith("/api"):
                return f"{raw}/v1"
            return f"{raw}/api/v1"
        path = cls.api_base_path(parts.path)
        return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")

    @classmethod
    def api_base_path(cls, path: str) -> str:
        parts = [item for item in path.strip("/").split("/") if item]
        if len(parts) >= 2 and parts[-2:] == ["api", "v1"]:
            return "/" + "/".join(parts)
        if parts and parts[-1] == "api":
            return "/" + "/".join([*parts, "v1"])
        if parts and parts[-1] in cls.FRONTEND_PAGE_SUFFIXES:
            parts = parts[:-1]
        return "/" + "/".join([*parts, "api", "v1"])

    @staticmethod
    def account_email(account: PlatformAccountMonitor) -> str:
        return (account.username or account.external_account_id or "").strip()

    @staticmethod
    def first_login_account(platform: RelayPlatform) -> PlatformAccountMonitor | None:
        return next(
            (
                account
                for account in platform.account_monitors
                if account.enabled
                and (account.username or account.external_account_id)
                and account.password_encrypted
            ),
            None,
        )

    @staticmethod
    def safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {}

    @staticmethod
    def unwrap_sub2api_response(payload: Any) -> tuple[Any, str | None]:
        if not isinstance(payload, dict) or "code" not in payload:
            return payload, None
        if payload.get("code") in (0, "0"):
            return payload.get("data"), None
        message = payload.get("message") or payload.get("detail") or payload.get("error")
        return None, str(message or f"code={payload.get('code')}")

    @classmethod
    def parse_group_catalog_payload(
        cls,
        groups_payload: Any,
        rates_payload: Any | None = None,
    ) -> list[DiscoveredGroupRateResult]:
        rows = cls.group_rows(groups_payload)
        user_rates = cls.normalized_rate_map(rates_payload)
        groups: list[DiscoveredGroupRateResult] = []
        for raw_group in rows:
            if not isinstance(raw_group, dict):
                continue
            group_id = raw_group.get("id")
            if group_id is None:
                continue
            external_group_id = str(group_id)
            name = str(raw_group.get("name") or external_group_id)
            base_rate = cls.number_from_value(raw_group.get("rate_multiplier"))
            rate_multiplier = user_rates.get(external_group_id, base_rate)
            rpm_limit = cls.int_from_value(raw_group.get("rpm_limit"))
            description = cls.group_description(raw_group, user_rates, external_group_id, base_rate)
            groups.append(
                DiscoveredGroupRateResult(
                    external_group_id=external_group_id,
                    name=name,
                    description=description,
                    rate_multiplier=rate_multiplier,
                    rpm_limit=rpm_limit,
                )
            )
        return groups

    @staticmethod
    def group_rows(groups_payload: Any) -> list[Any]:
        if isinstance(groups_payload, list):
            return groups_payload
        if not isinstance(groups_payload, dict):
            return []
        for key in ("items", "groups", "data"):
            value = groups_payload.get(key)
            if isinstance(value, list):
                return value
        return []

    @classmethod
    def normalized_rate_map(cls, rates_payload: Any | None) -> dict[str, float]:
        if not isinstance(rates_payload, dict):
            return {}
        result: dict[str, float] = {}
        for key, value in rates_payload.items():
            number = cls.number_from_value(value)
            if number is not None:
                result[str(key)] = number
        return result

    @classmethod
    def group_description(
        cls,
        raw_group: dict[str, Any],
        user_rates: dict[str, float],
        external_group_id: str,
        base_rate: float | None,
    ) -> str | None:
        parts: list[str] = []
        description = raw_group.get("description")
        if isinstance(description, str) and description.strip():
            parts.append(description.strip())
        platform = raw_group.get("platform")
        if isinstance(platform, str) and platform.strip():
            parts.append(f"平台: {platform.strip()}")
        if external_group_id in user_rates and base_rate is not None:
            parts.append(f"专属倍率覆盖: {base_rate:g} -> {user_rates[external_group_id]:g}")
        return "；".join(parts) if parts else None

    @classmethod
    def sum_api_key_quotas(cls, keys_payload: Any) -> tuple[float | None, float | None]:
        rows = cls.group_rows(keys_payload)
        quota_used = 0.0
        quota_limit = 0.0
        has_used = False
        has_limit = False
        for raw_key in rows:
            if not isinstance(raw_key, dict):
                continue
            used = cls.number_from_value(raw_key.get("quota_used"))
            if used is not None:
                quota_used += used
                has_used = True
            limit = cls.number_from_value(raw_key.get("quota"))
            if limit is not None and limit > 0:
                quota_limit += limit
                has_limit = True
        return quota_used if has_used else None, quota_limit if has_limit else None

    @classmethod
    def api_key_summaries(cls, keys_payload: Any) -> tuple[dict[str, str | None], ...]:
        summaries: list[dict[str, str | None]] = []
        for raw_key in cls.group_rows(keys_payload):
            if not isinstance(raw_key, dict):
                continue
            key_id = raw_key.get("id")
            name = raw_key.get("name")
            raw_group = raw_key.get("group")
            group = raw_group if isinstance(raw_group, dict) else {}
            group_id = raw_key.get("group_id")
            if group_id is None:
                group_id = group.get("id")
            group_name = group.get("name")
            summaries.append(
                {
                    "id": str(key_id) if key_id is not None else "",
                    "name": str(name or key_id or "未命名密钥"),
                    "group_id": str(group_id) if group_id is not None else None,
                    "group_name": str(group_name) if group_name else None,
                }
            )
        return tuple(summaries)

    @classmethod
    def parse_key_group_catalog(cls, keys_payload: Any) -> list[KeyGroupMonitorResult]:
        key_groups: dict[str, str] = {}
        for summary in cls.api_key_summaries(keys_payload):
            external_group_id = (summary.get("group_id") or "").strip()
            if not external_group_id or external_group_id == "0":
                continue
            name = (summary.get("group_name") or f"分组 {external_group_id}").strip()
            key_groups.setdefault(external_group_id, name or f"分组 {external_group_id}")
        return [
            KeyGroupMonitorResult(external_group_id=external_group_id, name=name)
            for external_group_id, name in key_groups.items()
        ]

    @staticmethod
    def number_from_value(value: Any) -> float | None:
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    @classmethod
    def int_from_value(cls, value: Any) -> int | None:
        number = cls.number_from_value(value)
        return int(number) if number is not None else None


class NewApiStrategy(ProviderStrategy):
    provider_type = "newapi"
    label = "New API"
    description = "面向 New API 部署实例的监控策略骨架"
    LOGIN_ENDPOINTS = ("api/user/login?turnstile=", "api/user/login")
    LOGIN_RATE_LIMIT_RETRY_DELAYS = (5.0, 15.0, 30.0, 60.0)
    ACCOUNT_LOGIN_SPACING_SECONDS = 2.0
    LOGIN_HEADER_CACHE_SECONDS = 30 * 60
    LOGIN_RETRY_JITTER_SECONDS = 2.0
    RATIO_SYNC_CHANNELS_ENDPOINT = "api/ratio_sync/channels"
    RATIO_SYNC_FETCH_ENDPOINT = "api/ratio_sync/fetch"
    CHANNEL_LIST_ENDPOINT = "api/channel/"
    CHANNEL_ID_PATTERN = re.compile(r"\(([^()]+)\)\s*$")

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        site_strategies: NewApiSiteStrategyRegistry | None = None,
    ) -> None:
        super().__init__(timeout_seconds)
        self.site_strategies = site_strategies or newapi_site_strategy_registry
        self._login_header_cache: dict[tuple[str, str], tuple[float, dict[str, str]]] = {}

    async def fetch_channel_catalog(
        self,
        platform: RelayPlatform,
    ) -> list[DiscoveredChannelRateResult] | None:
        management_headers = self.management_headers(platform)

        errors: list[str] = []
        attempted_user_ids: set[str] = set()
        if management_headers and "New-Api-User" in management_headers:
            attempted_user_id = management_headers.get("New-Api-User")
            if attempted_user_id:
                attempted_user_ids.add(attempted_user_id)
            try:
                return await self.fetch_channel_catalog_with_headers(platform, management_headers)
            except ValueError as exc:
                message = str(exc)
                errors.append(message)
                if not self.is_retryable_auth_error_message(message):
                    raise

        previous_login_site_url: str | None = None
        for account in platform.account_monitors:
            attempted_user_id = self.management_user_id_from_account(account)
            if attempted_user_id and attempted_user_id in attempted_user_ids:
                continue
            login_site_url = self.account_login_site_url(platform, account)
            if (
                previous_login_site_url is not None
                and login_site_url is not None
                and login_site_url == previous_login_site_url
            ):
                await asyncio.sleep(self.ACCOUNT_LOGIN_SPACING_SECONDS)
            headers = await self.login_management_headers_for_account(platform, account)
            if login_site_url is not None:
                previous_login_site_url = login_site_url
            if headers is None:
                continue
            attempted_user_id = headers.get("New-Api-User")
            if attempted_user_id:
                attempted_user_ids.add(attempted_user_id)
            try:
                return await self.fetch_channel_catalog_with_headers(platform, headers)
            except ValueError as exc:
                message = str(exc)
                errors.append(message)
                if not self.is_retryable_auth_error_message(message):
                    raise

        if errors and all(self.is_insufficient_privileges_message(error) for error in errors):
            return None
        if errors:
            raise ValueError(errors[-1])
        raise ValueError(
            "NewAPI 渠道倍率目录读取失败：缺少可用于登录的启用账号。"
            "请配置一个启用的登录账号，或在平台配置中填写有效的管理凭证。"
        )

    async def fetch_channel_catalog_with_headers(
        self,
        platform: RelayPlatform,
        headers: dict[str, str],
    ) -> list[DiscoveredChannelRateResult] | None:
        if "New-Api-User" not in headers:
            raise ValueError(
                "NewAPI 渠道倍率目录读取失败：缺少 New-Api-User。"
                "请在平台配置中填写管理用户 ID，或配置一个启用的登录账号。"
            )
        async with httpx.AsyncClient(
            base_url=self.site_url(platform),
            headers=headers,
            timeout=self.timeout_seconds,
        ) as client:
            channels_response = await client.get(self.RATIO_SYNC_CHANNELS_ENDPOINT)
            if (
                channels_response.status_code in {401, 403}
                and self.looks_like_invalid_token(channels_response)
            ):
                fallback_headers = None
                if "Authorization" in headers and "Cookie" in headers:
                    fallback_headers = dict(headers)
                    fallback_headers.pop("Authorization", None)
                else:
                    fallback_headers = await self.login_management_headers(platform, force_refresh=True)
                if fallback_headers is not None:
                    client.headers.clear()
                    client.headers.update(fallback_headers)
                    headers = dict(fallback_headers)
                    channels_response = await client.get(self.RATIO_SYNC_CHANNELS_ENDPOINT)
            channels_payload = self.safe_json(channels_response)
            if channels_response.status_code >= 400:
                message = self.response_message(channels_payload)
                if message:
                    raise ValueError(f"NewAPI 渠道倍率目录读取失败：上游提示：{message}")
                raise ValueError(
                    "NewAPI 渠道倍率目录读取失败："
                    f"{self.RATIO_SYNC_CHANNELS_ENDPOINT} 返回 HTTP {channels_response.status_code}。"
                    f"{self.response_debug_summary(channels_response, channels_payload)}。"
                    "请检查管理凭证是否有效，或当前账号是否有权限读取渠道倍率。"
                )
            if self.response_failed(channels_payload):
                message = self.response_message(channels_payload)
                raise ValueError(
                    f"NewAPI 渠道倍率目录读取失败：上游返回失败，提示：{message}"
                    if message
                    else (
                        "NewAPI 渠道倍率目录读取失败：上游返回失败，但没有提供明确提示。"
                        f"{self.response_debug_summary(channels_response, channels_payload)}。"
                    )
                )

            admin_channels_payload: Any | None = None
            try:
                admin_response = await client.get(self.CHANNEL_LIST_ENDPOINT)
            except httpx.HTTPError:
                admin_response = None
            if admin_response is not None and admin_response.status_code < 400:
                admin_payload = self.safe_json(admin_response)
                if not self.response_failed(admin_payload):
                    admin_channels_payload = admin_payload

            channel_ids = [
                int(channel_id)
                for channel_id in self.channel_ids_from_payload(channels_payload)
                if channel_id.isdigit() and int(channel_id) > 0
            ]
            if not channel_ids:
                return self.parse_channel_rate_results(
                    channels_payload,
                    admin_channels_payload=admin_channels_payload,
                )

            ratio_payload: Any | None = None
            ratio_error: str | None = None
            ratio_response = await client.post(
                self.RATIO_SYNC_FETCH_ENDPOINT,
                json={"channel_ids": channel_ids, "timeout": int(self.timeout_seconds)},
            )
            ratio_payload = self.safe_json(ratio_response)
            if ratio_response.status_code >= 400:
                ratio_error = (
                    "NewAPI 渠道模型倍率读取失败："
                    f"{self.RATIO_SYNC_FETCH_ENDPOINT} 返回 HTTP {ratio_response.status_code}。"
                    f"{self.response_debug_summary(ratio_response, ratio_payload)}。"
                )
            elif self.response_failed(ratio_payload):
                message = self.response_message(ratio_payload)
                ratio_error = (
                    f"NewAPI 渠道模型倍率读取失败：上游返回失败，提示：{message}"
                    if message
                    else (
                        "NewAPI 渠道模型倍率读取失败：上游返回失败，但没有提供明确提示。"
                        f"{self.response_debug_summary(ratio_response, ratio_payload)}。"
                    )
                )

        return self.parse_channel_rate_results(
            channels_payload,
            ratio_payload=ratio_payload,
            admin_channels_payload=admin_channels_payload,
            ratio_error=ratio_error,
        )

    async def fetch_account_balance(
        self,
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        strategy = self.site_strategies.get(platform.site_strategy)
        balance_result: AccountBalanceResult
        try:
            balance_result = await strategy.fetch_account_balance(self, platform, account)
        except Exception as exc:  # noqa: BLE001
            balance_result = AccountBalanceResult(error=str(exc))

        key_summaries: tuple[dict[str, str | None], ...] = balance_result.key_summaries
        key_summary_error: str | None = None
        if not (account.username and account.password_encrypted):
            try:
                fetched_key_summaries = await self.fetch_key_summaries(platform)
                if fetched_key_summaries:
                    key_summaries = fetched_key_summaries
            except Exception as exc:  # noqa: BLE001
                key_summary_error = str(exc)

        error = balance_result.error
        if key_summary_error:
            error = f"{error}; {key_summary_error}" if error else key_summary_error
        return AccountBalanceResult(
            balance=balance_result.balance,
            quota_used=balance_result.quota_used,
            quota_limit=balance_result.quota_limit,
            key_summaries=key_summaries,
            error=error,
        )

    async def fetch_group_rate(
        self,
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        strategy = self.site_strategies.get(platform.site_strategy)
        return await strategy.fetch_group_rate(self, platform, group)

    async def fetch_group_catalog(
        self,
        platform: RelayPlatform,
    ) -> list[DiscoveredGroupRateResult] | None:
        strategy = self.site_strategies.get(platform.site_strategy)
        return await strategy.fetch_group_catalog(self, platform)

    async def get_json(self, platform: RelayPlatform, path: str) -> tuple[int, Any, int]:
        platform_id = getattr(platform, "id", None)
        base_url = platform.base_url.rstrip("/")
        url = f"{base_url}/{path.lstrip('/')}"
        headers = await self.resolve_management_headers(platform)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(url, headers=headers)
        try:
            latency_ms = int(response.elapsed.total_seconds() * 1000)
        except Exception:  # noqa: BLE001
            latency_ms = 0
        if not response.headers.get("content-type", "").lower().startswith("application/json"):
            logger.debug(
                "newapi get non-json platform_id=%s path=%s status=%s latency_ms=%s",
                platform_id,
                path,
                response.status_code,
                latency_ms,
            )
            return response.status_code, {}, latency_ms
        if response.status_code >= 400:
            logger.warning(
                "newapi get failed platform_id=%s path=%s status=%s latency_ms=%s",
                platform_id,
                path,
                response.status_code,
                latency_ms,
            )
        return response.status_code, response.json(), latency_ms

    def management_headers(self, platform: RelayPlatform) -> dict[str, str]:
        headers: dict[str, str] = {}
        access_token = self.access_token_value(platform)
        if access_token:
            headers["Authorization"] = access_token
        user_id = self.management_user_id(platform)
        if user_id:
            headers["New-Api-User"] = user_id
        return headers

    async def resolve_management_headers(self, platform: RelayPlatform) -> dict[str, str]:
        headers = self.management_headers(platform)
        if "New-Api-User" in headers:
            return headers

        login_headers = await self.login_management_headers(platform)
        if login_headers is not None:
            for key, value in login_headers.items():
                if key == "Authorization" and key in headers:
                    continue
                headers[key] = value
        return headers

    async def login_management_headers(
        self,
        platform: RelayPlatform,
        *,
        force_refresh: bool = False,
    ) -> dict[str, str] | None:
        account = self.first_login_account(platform)
        return await self.login_management_headers_for_account(
            platform,
            account,
            force_refresh=force_refresh,
        )

    async def login_management_header_candidates(self, platform: RelayPlatform) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        previous_login_site_url: str | None = None
        for account in platform.account_monitors:
            login_site_url = self.account_login_site_url(platform, account)
            if (
                previous_login_site_url is not None
                and login_site_url is not None
                and login_site_url == previous_login_site_url
            ):
                await asyncio.sleep(self.ACCOUNT_LOGIN_SPACING_SECONDS)
            headers = await self.login_management_headers_for_account(platform, account)
            if login_site_url is not None:
                previous_login_site_url = login_site_url
            if headers is not None:
                candidates.append(headers)
        return candidates

    async def login_management_headers_for_account(
        self,
        platform: RelayPlatform,
        account: PlatformAccountMonitor | None,
        *,
        force_refresh: bool = False,
    ) -> dict[str, str] | None:
        if account is None or not account.username or not account.password_encrypted:
            return None
        if not account.enabled:
            return None

        password = decrypt_secret(account.password_encrypted)
        if not password:
            return None

        site_url = self.site_url(platform)
        if not force_refresh:
            cached_headers = self.cached_login_headers(site_url, account)
            if cached_headers is not None:
                return cached_headers

        request_headers = {
            "Accept": "application/json, text/plain, */*",
            "Cache-Control": "no-store",
            "Origin": self.site_origin(platform),
            "Referer": f"{site_url}login",
        }
        async with httpx.AsyncClient(
            base_url=site_url,
            follow_redirects=True,
            headers=request_headers,
            timeout=self.timeout_seconds,
        ) as client:
            await client.get("login")
            login_response, _ = await self.post_login_with_rate_limit_retry(
                client,
                self.LOGIN_ENDPOINTS,
                json={
                    "username": account.username,
                    "password": password,
                },
            )
            if login_response.status_code >= 400:
                return None
            login_payload = self.safe_json(login_response)
            if self.response_failed(login_payload):
                return None
            user_id = self.extract_user_id(login_payload)
            if user_id is None:
                return None

            headers: dict[str, str] = {"New-Api-User": str(user_id)}
            access_token = self.extract_access_token(login_payload)
            if access_token:
                headers["Authorization"] = f"Bearer {access_token}"
            cookie_header = self.session_cookie_header(login_response, client)
            if cookie_header:
                headers["Cookie"] = cookie_header
            self.cache_login_headers(site_url, account, headers)
            return headers

    def cached_login_headers(
        self,
        site_url: str,
        account: PlatformAccountMonitor | None,
    ) -> dict[str, str] | None:
        cache_key = self.login_header_cache_key(site_url, account)
        if cache_key is None:
            return None
        cached = self._login_header_cache.get(cache_key)
        if cached is None:
            return None
        expires_at, cached_headers = cached
        if expires_at <= monotonic():
            self._login_header_cache.pop(cache_key, None)
            return None
        return dict(cached_headers)

    def cache_login_headers(
        self,
        site_url: str,
        account: PlatformAccountMonitor | None,
        headers: dict[str, str],
    ) -> None:
        cache_key = self.login_header_cache_key(site_url, account)
        if cache_key is None:
            return
        self._login_header_cache[cache_key] = (
            monotonic() + self.LOGIN_HEADER_CACHE_SECONDS,
            dict(headers),
        )

    def drop_cached_login_headers(
        self,
        site_url: str,
        account: PlatformAccountMonitor | None,
    ) -> None:
        cache_key = self.login_header_cache_key(site_url, account)
        if cache_key is not None:
            self._login_header_cache.pop(cache_key, None)

    @staticmethod
    def login_header_cache_key(
        site_url: str,
        account: PlatformAccountMonitor | None,
    ) -> tuple[str, str] | None:
        if account is None or not account.username:
            return None
        username = account.username.strip().lower()
        if not username:
            return None
        return site_url.rstrip("/") + "/", username

    @staticmethod
    def first_login_account(platform: RelayPlatform) -> PlatformAccountMonitor | None:
        return next(
            (
                account
                for account in platform.account_monitors
                if account.enabled and account.username and account.password_encrypted
            ),
            None,
        )

    def account_login_site_url(
        self,
        platform: RelayPlatform,
        account: PlatformAccountMonitor | None,
    ) -> str | None:
        if account is None or not account.enabled:
            return None
        if not account.username or not account.password_encrypted:
            return None
        return self.site_url(platform)

    @staticmethod
    def access_token_value(platform: RelayPlatform) -> str | None:
        token = decrypt_secret(platform.api_key_encrypted)
        if not token:
            return None
        token = token.strip()
        if not token:
            return None
        prefix = (getattr(platform, "auth_header_prefix", None) or "").strip() or "Bearer"
        parts = token.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == prefix.lower():
            token = parts[1].strip()
        return f"{prefix} {token}" if token else None

    @staticmethod
    def management_user_id(platform: RelayPlatform) -> str | None:
        for account in platform.account_monitors:
            user_id = NewApiStrategy.management_user_id_from_account(account)
            if user_id:
                return user_id
        return None

    @staticmethod
    def management_user_id_from_account(account: PlatformAccountMonitor) -> str | None:
        if not account.enabled:
            return None
        for candidate in (getattr(account, "external_account_id", None), account.username):
            candidate = (candidate or "").strip()
            if not candidate:
                continue
            if candidate.lower().startswith("bearer "):
                candidate = candidate[7:].strip()
            if candidate.isdigit():
                return candidate
        return None

    @staticmethod
    def site_url(platform: RelayPlatform) -> str:
        parts = urlsplit(platform.base_url)
        if not parts.scheme or not parts.netloc:
            return platform.base_url.rstrip("/") + "/"
        path = NewApiStrategy.site_base_path(parts.path)
        return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/") + "/"

    @staticmethod
    def site_origin(platform: RelayPlatform) -> str:
        parts = urlsplit(platform.base_url)
        if not parts.scheme or not parts.netloc:
            return platform.base_url.rstrip("/")
        return urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")

    @staticmethod
    def site_base_path(path: str) -> str:
        path = path.strip("/")
        if not path:
            return ""
        parts = path.split("/")
        if parts[-1] in {"login", "register", "pricing"}:
            parts = parts[:-1]
        if parts and parts[-1] == "api":
            parts = parts[:-1]
        return "/" + "/".join(parts) if parts else ""

    @staticmethod
    def safe_json(response: httpx.Response) -> Any:
        if not response.headers.get("content-type", "").lower().startswith("application/json"):
            return {}
        try:
            return response.json()
        except ValueError:
            return {}

    @staticmethod
    def response_failed(payload: Any) -> bool:
        return isinstance(payload, dict) and payload.get("success") is False

    @staticmethod
    def response_message(payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        message = payload.get("message") or payload.get("msg") or payload.get("error")
        return str(message) if message else None

    @staticmethod
    def auth_debug_summary(headers: dict[str, str] | None) -> str:
        if not headers:
            return "none"
        parts = [
            f"authorization={'yes' if headers.get('Authorization') else 'no'}",
            f"new_api_user={'yes' if headers.get('New-Api-User') else 'no'}",
            f"cookie={'yes' if headers.get('Cookie') else 'no'}",
        ]
        extra_headers = sorted(
            key
            for key in headers
            if key not in {"Authorization", "New-Api-User", "Cookie"}
        )
        if extra_headers:
            parts.append(f"extra={','.join(extra_headers[:6])}")
        return " ".join(parts)

    @staticmethod
    def response_debug_summary(response: httpx.Response, payload: Any) -> str:
        content_type = response.headers.get("content-type", "").split(";", 1)[0] or "unknown"
        parts = [
            f"status={response.status_code}",
            f"content_type={content_type}",
        ]
        if isinstance(payload, dict):
            if payload:
                parts.append(f"json_keys={','.join(str(key) for key in list(payload)[:8])}")
                message = NewApiStrategy.response_message(payload)
                if message:
                    parts.append(f"message={NewApiStrategy.truncate_debug_text(message)!r}")
                if "success" in payload:
                    parts.append(f"success={payload.get('success')!r}")
            else:
                parts.append(f"body={NewApiStrategy.truncate_debug_text(response.text)!r}")
        elif isinstance(payload, list):
            parts.append("json_type=list")
            parts.append(f"json_len={len(payload)}")
        else:
            parts.append(f"body={NewApiStrategy.truncate_debug_text(response.text)!r}")
        return " ".join(parts)

    @staticmethod
    def truncate_debug_text(value: Any, limit: int = 180) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return f"{text[:limit]}..."

    @staticmethod
    def extract_user_id(payload: Any) -> int | str | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        user_id = data.get("id")
        if isinstance(user_id, int | str) and str(user_id):
            return user_id
        return None

    @staticmethod
    def extract_access_token(payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        candidates: list[Any] = [payload.get("data"), payload.get("result"), payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            for key in ("access_token", "accessToken", "token", "access", "jwt"):
                access_token = candidate.get(key)
                if isinstance(access_token, str) and access_token.strip():
                    return access_token.strip()
            auth = candidate.get("auth")
            if isinstance(auth, dict):
                for key in ("access_token", "accessToken", "token", "jwt"):
                    access_token = auth.get(key)
                    if isinstance(access_token, str) and access_token.strip():
                        return access_token.strip()
        return None

    @staticmethod
    def looks_like_invalid_token(response: httpx.Response) -> bool:
        text = response.text.lower()
        return "invalid access token" in text or "unauthorized" in text

    @staticmethod
    def is_retryable_auth_error_message(message: str) -> bool:
        text = message.lower()
        return "invalid access token" in text or "unauthorized" in text or "insufficient privileges" in text

    @staticmethod
    def is_insufficient_privileges_message(message: str) -> bool:
        text = message.lower()
        return "insufficient privileges" in text

    @staticmethod
    def session_cookie_header(response: httpx.Response, client: httpx.AsyncClient) -> str | None:
        session_value = response.cookies.get("session")
        client_cookies = getattr(client, "cookies", None)
        if not session_value and client_cookies is not None:
            session_value = client_cookies.get("session")
        if session_value:
            return f"session={session_value}"

        raw_set_cookie = response.headers.get("set-cookie")
        if not raw_set_cookie:
            return None
        parsed = SimpleCookie()
        try:
            parsed.load(raw_set_cookie)
        except Exception:  # noqa: BLE001
            return None
        session = parsed.get("session")
        if session is None or not session.value:
            return None
        return f"session={session.value}"

    @staticmethod
    async def get_first_available(
        client: httpx.AsyncClient,
        endpoints: tuple[str, ...],
    ) -> tuple[httpx.Response, str]:
        last_response: httpx.Response | None = None
        for endpoint in endpoints:
            response = await client.get(endpoint)
            if response.status_code != 404:
                return response, endpoint
            last_response = response
        if last_response is None:
            raise ValueError("no endpoints configured")
        return last_response, endpoints[-1]

    @staticmethod
    async def post_first_available(
        client: httpx.AsyncClient,
        endpoints: tuple[str, ...],
        retry_statuses: set[int] | frozenset[int] | tuple[int, ...] = (404,),
        **kwargs: Any,
    ) -> tuple[httpx.Response, str]:
        last_response: httpx.Response | None = None
        for endpoint in endpoints:
            response = await client.post(endpoint, **kwargs)
            if response.status_code not in retry_statuses:
                return response, endpoint
            last_response = response
        if last_response is None:
            raise ValueError("no endpoints configured")
        return last_response, endpoints[-1]

    async def post_login_with_rate_limit_retry(
        self,
        client: httpx.AsyncClient,
        endpoints: tuple[str, ...],
        **kwargs: Any,
    ) -> tuple[httpx.Response, str]:
        response, endpoint = await self.post_first_available(
            client,
            endpoints,
            retry_statuses={404},
            **kwargs,
        )
        for default_delay in self.LOGIN_RATE_LIMIT_RETRY_DELAYS:
            if response.status_code != 429:
                return response, endpoint
            delay = self.retry_after_seconds(response) or self.retry_delay_with_jitter(default_delay)
            await asyncio.sleep(delay)
            response, endpoint = await self.post_first_available(
                client,
                endpoints,
                retry_statuses={404},
                **kwargs,
            )
        return response, endpoint

    @staticmethod
    def retry_after_seconds(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            seconds = float(value)
        except ValueError:
            return None
        if seconds < 0:
            return None
        return min(seconds, 30.0)

    def retry_delay_with_jitter(self, default_delay: float) -> float:
        jitter = random.uniform(0.0, self.LOGIN_RETRY_JITTER_SECONDS)
        return default_delay + jitter

    async def fetch_key_summaries(
        self,
        platform: RelayPlatform,
    ) -> tuple[dict[str, str | None], ...]:
        platform_id = getattr(platform, "id", None)
        platform_name = getattr(platform, "name", None)
        headers = await self.resolve_management_headers(platform)
        logger.debug(
            "newapi token summaries start platform_id=%s platform_name=%s auth=%s",
            platform_id,
            platform_name,
            self.auth_debug_summary(headers),
        )
        async with httpx.AsyncClient(
            base_url=self.site_url(platform),
            headers=headers,
            timeout=self.timeout_seconds,
        ) as client:
            try:
                summaries = await self.fetch_token_summaries(client, string_group_as_id=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "newapi token summaries failed platform_id=%s platform_name=%s auth=%s error=%s",
                    platform_id,
                    platform_name,
                    self.auth_debug_summary(headers),
                    exc,
                )
                raise
            group_ids = sorted(
                {
                    str(summary.get("group_id"))
                    for summary in summaries
                    if summary.get("group_id")
                }
            )
            logger.info(
                "newapi token summaries fetched platform_id=%s platform_name=%s keys=%s groups=%s group_sample=%s auth=%s",
                platform_id,
                platform_name,
                len(summaries),
                len(group_ids),
                group_ids[:8],
                self.auth_debug_summary(headers),
            )
            return summaries

    async def fetch_token_summaries(
        self,
        client: httpx.AsyncClient,
        request_headers: dict[str, str] | None = None,
        string_group_as_id: bool = False,
    ) -> tuple[dict[str, str | None], ...] | None:
        token_ids: list[str] = []
        page = 1
        page_size = 100
        while True:
            response = await client.get(
                "api/token/",
                params={"p": page, "page": page, "page_size": page_size, "size": page_size},
                headers=request_headers,
            )
            payload = self.safe_json(response)
            if response.status_code >= 400:
                logger.warning(
                    "newapi token list failed page=%s status=%s summary=%s",
                    page,
                    response.status_code,
                    self.response_debug_summary(response, payload),
                )
                raise ValueError(
                    "NewAPI 密钥列表读取失败："
                    f"api/token/ 返回 HTTP {response.status_code}。"
                    f"{self.response_debug_summary(response, payload)}。"
                    "请检查管理凭证是否有效，或当前账号是否有权限读取密钥列表。"
                )
            if self.response_failed(payload):
                message = self.response_message(payload)
                logger.warning(
                    "newapi token list response failed page=%s summary=%s",
                    page,
                    self.response_debug_summary(response, payload),
                )
                raise ValueError(
                    f"NewAPI 密钥列表读取失败：上游返回失败，提示：{message}"
                    if message
                    else (
                        "NewAPI 密钥列表读取失败：上游返回失败，但没有提供明确提示。"
                        f"{self.response_debug_summary(response, payload)}。"
                    )
                )

            items, total, response_page_size = self.token_list_items(payload)
            logger.debug(
                "newapi token list page fetched page=%s items=%s total=%s page_size=%s",
                page,
                len(items),
                total,
                response_page_size,
            )
            for item in items:
                token_id = item.get("id")
                if token_id is None:
                    continue
                token_id_text = str(token_id).strip()
                if token_id_text:
                    token_ids.append(token_id_text)

            if not items:
                break
            if total is not None and len(token_ids) >= total:
                break
            if len(items) < response_page_size:
                break
            page += 1

        if not token_ids:
            logger.info("newapi token summaries fetched no tokens")
            return ()

        details = await self.fetch_token_details(client, token_ids, request_headers=request_headers)
        summaries: list[dict[str, str | None]] = []
        for token_id in token_ids:
            detail = details.get(token_id, {})
            name = self.string_value(detail.get("name")) or f"密钥 {token_id}"
            group_id, group_name = self.token_group_fields(
                detail,
                string_group_as_id=string_group_as_id,
            )
            summaries.append(
                {
                    "id": token_id,
                    "name": name,
                    "group_id": group_id,
                    "group_name": group_name,
                }
            )
        logger.debug(
            "newapi token summaries parsed keys=%s grouped_keys=%s string_group_as_id=%s",
            len(summaries),
            sum(1 for summary in summaries if summary.get("group_id")),
            string_group_as_id,
        )
        return tuple(summaries)

    async def fetch_token_details(
        self,
        client: httpx.AsyncClient,
        token_ids: list[str],
        request_headers: dict[str, str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        details: dict[str, dict[str, Any]] = {}
        for token_id in token_ids:
            response = await client.get(f"api/token/{token_id}", headers=request_headers)
            payload = self.safe_json(response)
            if response.status_code >= 400:
                logger.warning(
                    "newapi token detail failed token_id=%s status=%s summary=%s",
                    token_id,
                    response.status_code,
                    self.response_debug_summary(response, payload),
                )
                raise ValueError(
                    "NewAPI 密钥详情读取失败："
                    f"密钥 {token_id} 返回 HTTP {response.status_code}。"
                    f"{self.response_debug_summary(response, payload)}。"
                    "请检查管理凭证是否有效，或该密钥是否仍存在。"
                )
            if self.response_failed(payload):
                message = self.response_message(payload)
                logger.warning(
                    "newapi token detail response failed token_id=%s summary=%s",
                    token_id,
                    self.response_debug_summary(response, payload),
                )
                raise ValueError(
                    f"NewAPI 密钥详情读取失败：密钥 {token_id} 上游返回失败，提示：{message}"
                    if message
                    else (
                        f"NewAPI 密钥详情读取失败：密钥 {token_id} 上游返回失败，"
                        f"但没有提供明确提示。{self.response_debug_summary(response, payload)}。"
                    )
                )
            data = self.unwrap_payload(payload)
            if isinstance(data, dict):
                details[token_id] = data
                logger.debug(
                    "newapi token detail fetched token_id=%s keys=%s",
                    token_id,
                    list(data)[:8],
                )
            else:
                logger.warning(
                    "newapi token detail missing object token_id=%s payload_type=%s",
                    token_id,
                    type(data).__name__,
                )
        return details

    @staticmethod
    def token_list_items(payload: Any) -> tuple[list[dict[str, Any]], int | None, int]:
        data = NewApiStrategy.unwrap_payload(payload)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)], None, max(len(data), 1)
        if not isinstance(data, dict):
            return [], None, 1

        items = data.get("items")
        if isinstance(items, list):
            page_size = data.get("page_size", data.get("size"))
            if isinstance(page_size, int) and page_size > 0:
                response_page_size = page_size
            else:
                response_page_size = len(items) or 1
            total = data.get("total")
            total_count = None
            if isinstance(total, int):
                total_count = total
            elif isinstance(total, str) and total.isdigit():
                total_count = int(total)
            return [item for item in items if isinstance(item, dict)], total_count, response_page_size

        if all(isinstance(item, dict) for item in data.values()):
            return [item for item in data.values() if isinstance(item, dict)], None, max(len(data), 1)
        return [], None, 1

    @staticmethod
    def token_group_fields(
        token_detail: dict[str, Any],
        string_group_as_id: bool = False,
    ) -> tuple[str | None, str | None]:
        group_id = None
        group_name = None

        group = token_detail.get("group")
        if isinstance(group, dict):
            raw_group_id = group.get("id")
            if isinstance(raw_group_id, int | float):
                group_id = str(int(raw_group_id))
            elif isinstance(raw_group_id, str) and raw_group_id.strip():
                group_id = raw_group_id.strip()
            raw_group_name = group.get("name")
            if isinstance(raw_group_name, str) and raw_group_name.strip():
                group_name = raw_group_name.strip()
        elif isinstance(group, str) and group.strip():
            text = group.strip()
            if text.isdigit():
                group_id = text
            elif string_group_as_id:
                group_id = NewApiStrategy.group_id_from_display_name(text)
                group_name = text
            else:
                group_name = text

        raw_group_id = token_detail.get("group_id")
        if group_id is None:
            if isinstance(raw_group_id, int | float):
                group_id = str(int(raw_group_id))
            elif isinstance(raw_group_id, str) and raw_group_id.strip():
                group_id = raw_group_id.strip()

        raw_group_name = token_detail.get("group_name")
        if group_name is None and isinstance(raw_group_name, str) and raw_group_name.strip():
            group_name = raw_group_name.strip()

        if group_name is None and group_id is not None and not isinstance(group, dict):
            group_name = group_id

        return group_id, group_name

    @staticmethod
    def group_id_from_display_name(group_name: str) -> str:
        text = group_name.strip()
        if not text:
            return text
        for separator in ("（", "("):
            if separator in text:
                candidate = text.split(separator, 1)[0].strip()
                if candidate:
                    return candidate
        return text

    def management_client(self, platform: RelayPlatform) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.site_url(platform),
            headers=self.management_headers(platform),
            timeout=self.timeout_seconds,
        )

    @classmethod
    def unwrap_payload(cls, payload: Any) -> Any:
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    @classmethod
    def channel_ids_from_payload(cls, payload: Any) -> list[str]:
        return [
            channel_id
            for channel_id in (
                cls.channel_id_from_raw(channel.get("id"))
                for channel in cls.parse_channel_catalog_payload(payload)
            )
            if channel_id
        ]

    @classmethod
    def parse_channel_rate_results(
        cls,
        channels_payload: Any,
        ratio_payload: Any | None = None,
        admin_channels_payload: Any | None = None,
        ratio_error: str | None = None,
    ) -> list[DiscoveredChannelRateResult]:
        channels = cls.parse_channel_catalog_payload(channels_payload)
        admin_channels = {
            channel_id: channel
            for channel in cls.parse_channel_catalog_payload(admin_channels_payload)
            if (channel_id := cls.channel_id_from_raw(channel.get("id")))
        }
        model_rates_by_channel = cls.parse_ratio_sync_model_ratios(ratio_payload)

        results: list[DiscoveredChannelRateResult] = []
        for channel in channels:
            channel_id = cls.channel_id_from_raw(channel.get("id"))
            if not channel_id:
                continue
            merged_channel = dict(admin_channels.get(channel_id, {}))
            merged_channel.update(channel)
            model_rates = model_rates_by_channel.get(channel_id, {})
            rate_multiplier = (
                sum(model_rates.values()) / len(model_rates)
                if model_rates
                else None
            )
            name = cls.channel_value(merged_channel, ("name", "Name")) or f"渠道 {channel_id}"
            results.append(
                DiscoveredChannelRateResult(
                    external_channel_id=channel_id,
                    name=str(name)[:120],
                    description=cls.channel_description(merged_channel, model_rates),
                    base_url=cls.string_value(cls.channel_value(merged_channel, ("base_url", "BaseURL", "baseUrl"))),
                    status=cls.channel_status_label(cls.channel_value(merged_channel, ("status", "Status"))),
                    rate_multiplier=rate_multiplier,
                    model_rates=model_rates,
                    error=ratio_error,
                )
            )
        return results

    @classmethod
    def parse_channel_catalog_payload(cls, payload: Any) -> list[dict[str, Any]]:
        payload = cls.unwrap_payload(payload)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("channels", "items", "list", "rows", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = cls.parse_channel_catalog_payload(value)
                if nested:
                    return nested
        if all(isinstance(item, dict) for item in payload.values()):
            return [item for item in payload.values() if isinstance(item, dict)]
        return []

    @classmethod
    def parse_ratio_sync_model_ratios(cls, ratio_payload: Any | None) -> dict[str, dict[str, float]]:
        data = cls.unwrap_payload(ratio_payload)
        if not isinstance(data, dict):
            return {}
        differences = data.get("differences")
        if not isinstance(differences, dict):
            return {}

        rates: dict[str, dict[str, float]] = {}
        if isinstance(differences.get("model_ratio"), dict):
            for model_name, ratio_item in differences["model_ratio"].items():
                cls.collect_model_ratio(rates, str(model_name), ratio_item)
            return rates

        for model_name, ratio_types in differences.items():
            if not isinstance(ratio_types, dict):
                continue
            ratio_item = ratio_types.get("model_ratio")
            if ratio_item is None:
                continue
            cls.collect_model_ratio(rates, str(model_name), ratio_item)
        return rates

    @classmethod
    def collect_model_ratio(
        cls,
        rates: dict[str, dict[str, float]],
        model_name: str,
        ratio_item: Any,
    ) -> None:
        if not isinstance(ratio_item, dict):
            return
        current = cls.number_from_value(ratio_item.get("current"))
        upstreams = ratio_item.get("upstreams")
        if not isinstance(upstreams, dict):
            upstreams = {
                key: value
                for key, value in ratio_item.items()
                if cls.channel_id_from_label(str(key)) is not None
            }
        for label, raw_value in upstreams.items():
            channel_id = cls.channel_id_from_label(str(label))
            if not channel_id:
                continue
            value = (
                current
                if isinstance(raw_value, str) and raw_value.lower() == "same"
                else cls.number_from_value(raw_value)
            )
            if value is None:
                continue
            rates.setdefault(channel_id, {})[model_name] = value

    @classmethod
    def channel_description(cls, channel: dict[str, Any], model_rates: dict[str, float]) -> str | None:
        parts: list[str] = []
        channel_type = cls.channel_value(channel, ("type", "Type"))
        if channel_type is not None:
            parts.append(f"类型: {channel_type}")
        groups = cls.channel_value(channel, ("group", "Group"))
        if groups:
            parts.append(f"分组: {cls.join_channel_value(groups)}")
        models = cls.channel_value(channel, ("models", "Models"))
        if models:
            parts.append(f"模型: {cls.join_channel_value(models, limit=6)}")
        if model_rates:
            samples = [f"{name}={cls.trim_number(rate)}" for name, rate in list(model_rates.items())[:6]]
            suffix = f" 等 {len(model_rates)} 个" if len(model_rates) > 6 else ""
            parts.append(f"模型倍率: {', '.join(samples)}{suffix}")
        return "；".join(parts) if parts else None

    @staticmethod
    def join_channel_value(value: Any, limit: int | None = None) -> str:
        if isinstance(value, list | tuple):
            items = [str(item) for item in value if item is not None]
        else:
            items = [item.strip() for item in str(value).split(",") if item.strip()]
        if limit is not None and len(items) > limit:
            return f"{', '.join(items[:limit])} 等 {len(items)} 个"
        return ", ".join(items)

    @staticmethod
    def channel_value(channel: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in channel:
                return channel[key]
        return None

    @staticmethod
    def string_value(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @classmethod
    def channel_id_from_raw(cls, value: Any) -> str | None:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @classmethod
    def channel_id_from_label(cls, value: str) -> str | None:
        match = cls.CHANNEL_ID_PATTERN.search(value)
        if match:
            return match.group(1).strip()
        stripped = value.strip()
        return stripped if stripped.isdigit() else None

    @staticmethod
    def channel_status_label(value: Any) -> str | None:
        if value is None:
            return None
        status_map = {
            "0": "禁用",
            "1": "启用",
            "2": "自动禁用",
            "3": "手动禁用",
        }
        return status_map.get(str(value), str(value))

    @staticmethod
    def number_from_value(value: Any) -> float | None:
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def trim_number(value: float) -> str:
        return f"{value:.6f}".rstrip("0").rstrip(".")


class ProviderRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, ProviderStrategy] = {}

    def register(self, strategy: ProviderStrategy) -> None:
        self._strategies[strategy.provider_type] = strategy

    def get(self, provider_type: str) -> ProviderStrategy:
        if provider_type not in self._strategies:
            supported = ", ".join(sorted(self._strategies))
            raise ValueError(f"Unsupported provider type {provider_type!r}; supported: {supported}")
        return self._strategies[provider_type]

    def options(self) -> list[dict[str, str]]:
        return [
            {
                "value": strategy.provider_type,
                "label": strategy.label,
                "description": strategy.description,
            }
            for strategy in self._strategies.values()
        ]


provider_registry = ProviderRegistry()
newapi_site_strategy_registry = NewApiSiteStrategyRegistry()
newapi_site_strategy_registry.register(GenericNewApiSiteStrategy())
provider_registry.register(Sub2ApiStrategy())
provider_registry.register(NewApiStrategy())
