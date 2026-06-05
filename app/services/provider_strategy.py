from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.security import decrypt_secret
from app.models.monitor import PlatformAccountMonitor, PlatformGroupMonitor
from app.models.platform import RelayPlatform


@dataclass(frozen=True)
class AccountBalanceResult:
    balance: float | None = None
    quota_used: float | None = None
    quota_limit: float | None = None
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


class ProviderStrategy(ABC):
    provider_type: str
    label: str
    description: str

    def __init__(self, timeout_seconds: float = 15.0) -> None:
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
        latency_ms = int(response.elapsed.total_seconds() * 1000)
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
    site_strategy = "generic"
    label = "通用 New API"
    description = "通用占位策略，按 /api/group/{group_id} 读取倍率字段"

    async def fetch_account_balance(
        self,
        provider: "NewApiStrategy",
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
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

    async def fetch_group_rate(
        self,
        provider: "NewApiStrategy",
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        status, payload, _ = await provider.get_json(platform, f"/api/group/{group.external_group_id}")
        if status >= 400:
            return GroupRateResult(error=f"newapi group endpoint returned HTTP {status}")
        rate = provider.first_number(payload, ("rate_multiplier", "ratio", "multiplier"))
        rpm = provider.first_number(payload, ("rpm_limit", "rpm"))
        return GroupRateResult(rate_multiplier=rate, rpm_limit=int(rpm) if rpm is not None else None)


class YunjinNewApiSiteStrategy(NewApiSiteStrategy):
    DEFAULT_QUOTA_PER_UNIT = 500_000
    LOGIN_ENDPOINTS = ("api/user/login?turnstile=", "api/user/login")
    PRICING_ENDPOINTS = ("api/pricing", "pricing")
    GROUPS_ENDPOINT = "api/user/self/groups"

    site_strategy = "yunjin"
    label = "云锦"
    description = "云锦站点策略：账号登录后读取 /api/user/self，分组读取 /api/user/self/groups"

    async def fetch_account_balance(
        self,
        provider: "NewApiStrategy",
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        if not account.username or not account.password_encrypted:
            return AccountBalanceResult(error="云锦账号余额监控需要配置账号和密码")

        password = decrypt_secret(account.password_encrypted)
        if not password:
            return AccountBalanceResult(error="云锦账号余额监控密码解密失败或为空")

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
            await client.get("login")
            login_response, login_endpoint = await self.post_first_available(
                client,
                self.LOGIN_ENDPOINTS,
                json={
                    "username": account.username,
                    "password": password,
                },
            )
            if login_response.status_code >= 400:
                return AccountBalanceResult(
                    error=(
                        "yunjin login endpoint returned "
                        f"HTTP {login_response.status_code}: {login_endpoint}"
                    )
                )
            login_payload_json = self.safe_json(login_response)
            if isinstance(login_payload_json, dict) and login_payload_json.get("success") is False:
                message = login_payload_json.get("message") or "登录失败"
                return AccountBalanceResult(error=f"yunjin login failed: {message}")

            user_id = self.extract_user_id(login_payload_json)
            if user_id is None:
                return AccountBalanceResult(error="yunjin login response missing data.id")

            self_response = await client.get(
                "api/user/self",
                headers={"New-Api-User": str(user_id)},
            )
            if self_response.status_code >= 400:
                return AccountBalanceResult(
                    error=f"yunjin self endpoint returned HTTP {self_response.status_code}"
                )
            payload = self.safe_json(self_response)

        quota = provider.first_number(payload, ("quota",))
        if quota is None:
            return AccountBalanceResult(error="yunjin self response missing numeric data.quota")
        used_quota = provider.first_number(payload, ("used_quota",))
        return AccountBalanceResult(
            balance=quota / quota_per_unit,
            quota_used=used_quota / quota_per_unit if used_quota is not None else None,
        )

    async def fetch_group_rate(
        self,
        provider: "NewApiStrategy",
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        async with httpx.AsyncClient(
            base_url=self.site_url(platform),
            timeout=provider.timeout_seconds,
        ) as client:
            response, pricing_endpoint = await self.get_first_available(
                client,
                self.PRICING_ENDPOINTS,
            )
        if response.status_code >= 400:
            return GroupRateResult(
                error=(
                    "yunjin pricing endpoint returned "
                    f"HTTP {response.status_code}: {pricing_endpoint}"
                )
            )
        payload = self.safe_json(response)
        if not isinstance(payload, dict) or not isinstance(payload.get("group_ratio"), dict):
            return GroupRateResult(error="yunjin pricing response missing group_ratio")
        raw_rate = payload["group_ratio"].get(group.external_group_id)
        if raw_rate is None:
            return GroupRateResult(
                error=f"yunjin group_ratio missing group {group.external_group_id!r}"
            )
        try:
            return GroupRateResult(rate_multiplier=float(raw_rate))
        except (TypeError, ValueError):
            return GroupRateResult(error=f"yunjin group ratio is not numeric: {raw_rate!r}")

    async def fetch_group_catalog(
        self,
        provider: "NewApiStrategy",
        platform: RelayPlatform,
    ) -> list[DiscoveredGroupRateResult] | None:
        account = next(
            (
                item
                for item in platform.account_monitors
                if item.enabled and item.username and item.password_encrypted
            ),
            None,
        )
        if account is None:
            raise ValueError("yunjin group catalog fetch requires an enabled account with password")

        password = decrypt_secret(account.password_encrypted)
        if not password:
            raise ValueError("yunjin group catalog password decrypt failed or empty")

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
            await client.get("login")
            login_response, login_endpoint = await self.post_first_available(
                client,
                self.LOGIN_ENDPOINTS,
                json={
                    "username": account.username,
                    "password": password,
                },
            )
            if login_response.status_code >= 400:
                raise ValueError(
                    "yunjin group catalog login endpoint returned "
                    f"HTTP {login_response.status_code}: {login_endpoint}"
                )
            login_payload_json = self.safe_json(login_response)
            if isinstance(login_payload_json, dict) and login_payload_json.get("success") is False:
                message = login_payload_json.get("message") or "登录失败"
                raise ValueError(f"yunjin group catalog login failed: {message}")

            user_id = self.extract_user_id(login_payload_json)
            if user_id is None:
                raise ValueError("yunjin group catalog login response missing data.id")

            response = await client.get(
                self.GROUPS_ENDPOINT,
                headers={"New-Api-User": str(user_id)},
            )
            if response.status_code >= 400:
                raise ValueError(
                    f"yunjin group catalog endpoint returned HTTP {response.status_code}"
                )
            payload = self.safe_json(response)

        groups = self.parse_group_catalog_payload(payload)
        if groups is None:
            raise ValueError("yunjin group catalog response missing data")
        return groups

    @staticmethod
    def parse_group_catalog_payload(payload: Any) -> list[DiscoveredGroupRateResult] | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            return None

        groups: list[DiscoveredGroupRateResult] = []
        for external_group_id, raw_group in data.items():
            if not isinstance(external_group_id, str) or not external_group_id.strip():
                continue
            name = external_group_id.strip()
            description: str | None = None
            rate_multiplier: float | None = None
            rpm_limit: int | None = None
            error: str | None = None

            if isinstance(raw_group, dict):
                desc = raw_group.get("desc")
                if isinstance(desc, str) and desc.strip():
                    description = desc.strip()
                raw_ratio = raw_group.get("ratio")
                if raw_ratio is not None:
                    try:
                        rate_multiplier = float(raw_ratio)
                    except (TypeError, ValueError):
                        error = f"yunjin group ratio is not numeric: {raw_ratio!r}"
                raw_rpm = raw_group.get("rpm_limit", raw_group.get("rpm"))
                if raw_rpm is not None:
                    try:
                        rpm_limit = int(float(raw_rpm))
                    except (TypeError, ValueError):
                        if error is None:
                            error = f"yunjin group rpm is not numeric: {raw_rpm!r}"
            else:
                error = f"yunjin group payload is not an object: {raw_group!r}"

            groups.append(
                DiscoveredGroupRateResult(
                    external_group_id=name,
                    name=name,
                    description=description,
                    rate_multiplier=rate_multiplier,
                    rpm_limit=rpm_limit,
                    error=error,
                )
            )
        return groups

    @staticmethod
    def site_url(platform: RelayPlatform) -> str:
        parts = urlsplit(platform.base_url)
        if not parts.scheme or not parts.netloc:
            return platform.base_url.rstrip("/")
        path = YunjinNewApiSiteStrategy.site_base_path(parts.path)
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
        **kwargs: Any,
    ) -> tuple[httpx.Response, str]:
        last_response: httpx.Response | None = None
        for endpoint in endpoints:
            response = await client.post(endpoint, **kwargs)
            if response.status_code != 404:
                return response, endpoint
            last_response = response
        if last_response is None:
            raise ValueError("no endpoints configured")
        return last_response, endpoints[-1]


class NewApiSiteStrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, NewApiSiteStrategy] = {}

    def register(self, strategy: NewApiSiteStrategy) -> None:
        self._strategies[strategy.site_strategy] = strategy

    def get(self, site_strategy: str) -> NewApiSiteStrategy:
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
        if quota_used is None:
            quota_used = key_quota_used
        quota_limit = total_recharged if total_recharged is not None else key_quota_limit

        if dashboard_error and quota_used is None:
            return AccountBalanceResult(
                balance=balance,
                quota_limit=quota_limit,
                error=dashboard_error,
            )

        return AccountBalanceResult(
            balance=balance,
            quota_used=quota_used,
            quota_limit=quota_limit,
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

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        site_strategies: NewApiSiteStrategyRegistry | None = None,
    ) -> None:
        super().__init__(timeout_seconds)
        self.site_strategies = site_strategies or newapi_site_strategy_registry

    async def fetch_account_balance(
        self,
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        strategy = self.site_strategies.get(platform.site_strategy)
        return await strategy.fetch_account_balance(self, platform, account)

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
newapi_site_strategy_registry.register(YunjinNewApiSiteStrategy())
provider_registry.register(Sub2ApiStrategy())
provider_registry.register(NewApiStrategy())
