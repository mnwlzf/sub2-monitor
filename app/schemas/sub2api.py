from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Sub2APIDatabaseConfigResponse(BaseModel):
    configured: bool
    host: str
    port: int
    user: str
    dbname: str
    sslmode: str
    has_password: bool
    dsn: str | None
    connect_timeout_seconds: int


class Sub2APIDatabaseProbeResponse(BaseModel):
    ok: bool
    error: str | None = None
    current_database: str | None = None
    current_user: str | None = None
    server_version: str | None = None


class Sub2APIDatabaseStatusResponse(BaseModel):
    config: Sub2APIDatabaseConfigResponse
    probe: Sub2APIDatabaseProbeResponse | None = None


class Sub2APISQLLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    operation: str
    target_database: str
    sql_text: str
    sql_params_json: str | None
    status: str
    affected_rows: int | None
    error_message: str | None
    executed_by_user_id: int | None
    executed_by_username: str | None
    created_at: datetime


class Sub2APISQLLogPageResponse(BaseModel):
    items: list[Sub2APISQLLogResponse]
    total: int
    limit: int
    offset: int


class Sub2APIPrioritySyncGroupItem(BaseModel):
    external_group_id: str
    name: str
    source: str
    rate_multiplier: float | None
    rate_factor: float | None
    effective_rate_multiplier: float | None
    rpm_limit: int | None
    last_error: str | None


class Sub2APIPrioritySyncItem(BaseModel):
    platform_id: int
    platform_name: str
    base_url: str
    normalized_base_url: str
    rate_factor: float | None
    candidate_groups: list[Sub2APIPrioritySyncGroupItem]
    selected_group: Sub2APIPrioritySyncGroupItem | None
    effective_rate_multiplier: float | None
    priority: int | None
    status: str
    matched_accounts: int | None
    updated_accounts: int | None
    sql_log_id: int | None
    error_message: str | None


class Sub2APIPrioritySyncRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    target_database: str
    total_items: int
    succeeded_items: int
    failed_items: int
    skipped_items: int
    matched_accounts: int
    updated_accounts: int
    error_message: str | None
    items: list[Sub2APIPrioritySyncItem]
    executed_by_user_id: int | None
    executed_by_username: str | None
    created_at: datetime
    completed_at: datetime | None


class Sub2APIPrioritySyncRunPageResponse(BaseModel):
    items: list[Sub2APIPrioritySyncRunResponse]
    total: int
    limit: int
    offset: int
