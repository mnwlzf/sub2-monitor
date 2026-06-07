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
    from_name: str | None
    notify_group_rate_changes: bool
    notify_low_balance: bool
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
    from_name: str | None = Field(default=None, max_length=255)
    notify_group_rate_changes: bool = True
    notify_low_balance: bool = False

    @field_validator("from_email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("邮箱格式无效")
        return value

    @field_validator("from_name")
    @classmethod
    def normalize_from_name(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return value.strip()


class NotificationRecipientBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=255)
    enabled: bool = True

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("邮箱格式无效")
        return value


class NotificationRecipientCreate(NotificationRecipientBase):
    pass


class NotificationRecipientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    enabled: bool | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("邮箱格式无效")
        return value


class NotificationRecipientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    enabled: bool
    last_error: str | None
    last_tested_at: datetime | None
    created_at: datetime
    updated_at: datetime
