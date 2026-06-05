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
        status, payload, _ = await provider.get_json(platform, f"/{self.GROUPS_ENDPOINT}")
        if status >= 400:
            return None
        return self.parse_group_catalog_payload(payload)

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
    description = "面向 Sub2API 部署实例的监控策略骨架"

    async def fetch_account_balance(
        self,
        platform: RelayPlatform,
        account: PlatformAccountMonitor,
    ) -> AccountBalanceResult:
        status, payload, _ = await self.get_json(
            platform,
            f"/api/v1/admin/accounts/{account.external_account_id}",
        )
        if status >= 400:
            return AccountBalanceResult(error=f"sub2api account endpoint returned HTTP {status}")
        return AccountBalanceResult(
            balance=self.first_number(payload, ("balance", "remaining_balance", "quota_remaining")),
            quota_used=self.first_number(payload, ("quota_used", "used_quota", "usage")),
            quota_limit=self.first_number(payload, ("quota", "quota_limit", "limit")),
        )

    async def fetch_group_rate(
        self,
        platform: RelayPlatform,
        group: PlatformGroupMonitor,
    ) -> GroupRateResult:
        status, payload, _ = await self.get_json(
            platform,
            f"/api/v1/admin/groups/{group.external_group_id}",
        )
        if status >= 400:
            return GroupRateResult(error=f"sub2api group endpoint returned HTTP {status}")
        rate = self.first_number(payload, ("rate_multiplier", "multiplier", "rate"))
        rpm = self.first_number(payload, ("rpm_limit", "rpm", "request_per_minute"))
        return GroupRateResult(rate_multiplier=rate, rpm_limit=int(rpm) if rpm is not None else None)


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
