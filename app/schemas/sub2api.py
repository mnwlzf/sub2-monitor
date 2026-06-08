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
