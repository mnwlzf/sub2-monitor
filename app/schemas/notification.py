from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotificationSettingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    has_smtp_password: bool
    smtp_use_ssl: bool
    smtp_use_tls: bool
    from_email: str | None
    recipient_email: str | None
    last_error: str | None
    last_tested_at: datetime | None
    updated_at: datetime


class NotificationSettingUpdate(BaseModel):
    enabled: bool = False
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_password: str | None = Field(default=None, max_length=4096)
    smtp_use_ssl: bool = False
    smtp_use_tls: bool = True
    from_email: str | None = Field(default=None, max_length=255)
    recipient_email: str | None = Field(default=None, max_length=255)

    @field_validator("from_email", "recipient_email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("邮箱格式无效")
        return value
