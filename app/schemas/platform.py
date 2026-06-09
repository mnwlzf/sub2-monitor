from datetime import datetime

from croniter import CroniterBadCronError, croniter
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from pydantic import field_validator

from app.models.platform import PlatformStatus


class ProviderOption(BaseModel):
    value: str
    label: str
    description: str


class SiteStrategyOption(BaseModel):
    value: str
    label: str
    provider_type: str
    description: str


class PlatformBase(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base_url: HttpUrl
    provider_type: str = Field(default="sub2api", max_length=64)
    site_strategy: str = Field(default="generic", max_length=64)
    auth_header_name: str = Field(default="Authorization", max_length=64)
    auth_header_prefix: str = Field(default="Bearer", max_length=32)
    api_key: str | None = Field(default=None, max_length=4096)
    balance_cron: str = Field(default="*/10 * * * *", max_length=64)
    rate_cron: str = Field(default="0 * * * *", max_length=64)
    recharge_amount: float = Field(default=1.0, gt=0)
    received_amount: float = Field(default=1.0, gt=0)
    enabled: bool = True
    key_count: int = Field(default=0, ge=0)
    balance: float | None = None
    quota_used: float | None = Field(default=None, ge=0)
    quota_limit: float | None = Field(default=None, ge=0)
    low_balance_threshold: float | None = Field(default=None, ge=0)

    @field_validator("balance_cron", "rate_cron")
    @classmethod
    def validate_cron(cls, value: str) -> str:
        value = value.strip()
        try:
            croniter(value)
        except CroniterBadCronError as exc:
            raise ValueError("cron 表达式无效") from exc
        return value


class PlatformCreate(PlatformBase):
    pass


class PlatformUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: HttpUrl | None = None
    provider_type: str | None = Field(default=None, max_length=64)
    site_strategy: str | None = Field(default=None, max_length=64)
    auth_header_name: str | None = Field(default=None, max_length=64)
    auth_header_prefix: str | None = Field(default=None, max_length=32)
    api_key: str | None = Field(default=None, max_length=4096)
    balance_cron: str | None = Field(default=None, max_length=64)
    rate_cron: str | None = Field(default=None, max_length=64)
    recharge_amount: float | None = Field(default=None, gt=0)
    received_amount: float | None = Field(default=None, gt=0)
    enabled: bool | None = None
    key_count: int | None = Field(default=None, ge=0)
    balance: float | None = None
    quota_used: float | None = Field(default=None, ge=0)
    quota_limit: float | None = Field(default=None, ge=0)
    low_balance_threshold: float | None = Field(default=None, ge=0)
    status: PlatformStatus | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    last_error: str | None = None

    @field_validator("balance_cron", "rate_cron")
    @classmethod
    def validate_cron(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        try:
            croniter(value)
        except CroniterBadCronError as exc:
            raise ValueError("cron 表达式无效") from exc
        return value


class PlatformResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    base_url: str
    provider_type: str
    site_strategy: str
    auth_header_name: str
    auth_header_prefix: str
    has_api_key: bool
    balance_cron: str
    rate_cron: str
    recharge_amount: float
    received_amount: float
    effective_rate_factor: float | None
    balance_last_run_at: datetime | None
    balance_next_run_at: datetime | None
    rate_last_run_at: datetime | None
    rate_next_run_at: datetime | None
    status: PlatformStatus
    enabled: bool
    key_count: int
    balance: float | None
    quota_used: float | None
    quota_limit: float | None
    today_quota_used: float | None = None
    low_balance_threshold: float | None
    low_balance_notify_count: int
    latency_ms: int | None
    last_error: str | None
    checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SnapshotCreate(BaseModel):
    status: PlatformStatus
    balance: float | None = None
    quota_used: float | None = Field(default=None, ge=0)
    quota_limit: float | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    error_message: str | None = None


class PlatformErrorClearRequest(BaseModel):
    source: str
    target_id: int


class AccountMonitorBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    external_account_id: str = Field(min_length=1, max_length=120)
    username: str | None = Field(default=None, max_length=160)
    password: str | None = Field(default=None, max_length=4096)
    enabled: bool = True


class AccountMonitorCreate(AccountMonitorBase):
    pass


class AccountMonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    external_account_id: str | None = Field(default=None, min_length=1, max_length=120)
    username: str | None = Field(default=None, max_length=160)
    password: str | None = Field(default=None, max_length=4096)
    enabled: bool | None = None


class AccountKeySummary(BaseModel):
    id: str
    name: str
    group_id: str | None = None
    group_name: str | None = None


class AccountMonitorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    name: str
    external_account_id: str
    username: str | None
    has_password: bool
    enabled: bool
    balance: float | None
    quota_used: float | None
    quota_limit: float | None
    today_quota_used: float | None = None
    key_summaries: list[AccountKeySummary] = Field(default_factory=list)
    last_error: str | None
    checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GroupMonitorBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    external_group_id: str = Field(min_length=1, max_length=120)
    enabled: bool = True


class GroupMonitorCreate(GroupMonitorBase):
    pass


class GroupMonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    external_group_id: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None


class GroupMonitorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    name: str
    external_group_id: str
    enabled: bool
    rate_multiplier: float | None
    effective_rate_multiplier: float | None = None
    rpm_limit: int | None
    last_error: str | None
    checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DiscoveredGroupRateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    external_group_id: str
    name: str
    description: str | None
    rate_multiplier: float | None
    effective_rate_multiplier: float | None = None
    rpm_limit: int | None
    last_error: str | None
    checked_at: datetime | None
    configured_monitor_id: int | None = None
    is_configured: bool = False
    created_at: datetime
    updated_at: datetime


class DiscoveredChannelRateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    external_channel_id: str
    name: str
    description: str | None
    base_url: str | None
    status: str | None
    rate_multiplier: float | None
    model_rates: dict[str, float]
    last_error: str | None
    checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlatformDetailResponse(PlatformResponse):
    account_monitors: list[AccountMonitorResponse]
    group_monitors: list[GroupMonitorResponse]
    discovered_group_rates: list[DiscoveredGroupRateResponse]
    discovered_channel_rates: list[DiscoveredChannelRateResponse]

    @model_validator(mode="before")
    @classmethod
    def dedupe_discovered_group_rates(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        rows = value.get("discovered_group_rates")
        if not isinstance(rows, list):
            return value
        deduped: dict[str, object] = {}
        for row in rows:
            if isinstance(row, dict):
                key = row.get("external_group_id")
            else:
                key = getattr(row, "external_group_id", None)
            if key:
                deduped[str(key)] = row
        result = dict(value)
        result["discovered_group_rates"] = list(deduped.values())
        return result


class MonitorRunResponse(BaseModel):
    platform: PlatformResponse
    account_monitors: list[AccountMonitorResponse]
    group_monitors: list[GroupMonitorResponse]
    discovered_channel_rates: list[DiscoveredChannelRateResponse] = Field(default_factory=list)


class AccountBalanceHistoryPoint(BaseModel):
    at: datetime
    balance: float | None
    quota_used: float | None
    quota_limit: float | None


class AccountBalanceHistorySeries(BaseModel):
    account_id: int
    account_name: str
    points: list[AccountBalanceHistoryPoint]


class GroupRateHistoryPoint(BaseModel):
    at: datetime
    rate_multiplier: float | None
    effective_rate_multiplier: float | None
    rpm_limit: int | None


class GroupRateHistorySeries(BaseModel):
    group_id: int | None = None
    external_group_id: str
    group_name: str
    description: str | None = None
    configured_monitor_id: int | None = None
    is_configured: bool = False
    points: list[GroupRateHistoryPoint]


class EmbeddedHistoryResponse(BaseModel):
    balances: dict[int, list[AccountBalanceHistorySeries]]
    rates: dict[int, list[GroupRateHistorySeries]]


class DashboardStats(BaseModel):
    total_platforms: int
    enabled_platforms: int
    healthy_platforms: int
    degraded_platforms: int
    down_platforms: int
    total_keys: int
    account_monitor_count: int
    group_monitor_count: int
    average_latency_ms: int | None
    today_quota_used: float | None = None
