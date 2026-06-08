from pydantic import BaseModel


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
