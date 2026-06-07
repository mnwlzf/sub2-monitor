from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import encrypt_secret
from app.models.notification import NotificationRecipient
from app.schemas.notification import (
    NotificationRecipientCreate,
    NotificationRecipientResponse,
    NotificationRecipientUpdate,
    NotificationSettingResponse,
    NotificationSettingUpdate,
)
from app.services.notification import get_notification_setting, notification_config_errors, send_test_email

router = APIRouter(tags=["notifications"])


@router.get("/notification-settings", response_model=NotificationSettingResponse)
def get_settings(db: Session = Depends(get_db)):
    return get_notification_setting(db)


@router.put("/notification-settings", response_model=NotificationSettingResponse)
def update_settings(payload: NotificationSettingUpdate, db: Session = Depends(get_db)):
    setting = get_notification_setting(db)
    data = payload.model_dump()
    smtp_password = data.pop("smtp_password", None)
    for field, value in data.items():
        setattr(setting, field, value)
    if smtp_password:
        setting.smtp_password_encrypted = encrypt_secret(smtp_password)
    if not notification_config_errors(setting) and setting.last_error:
        incomplete_config_markers = (
            "邮件通知配置不完整",
            "邮件通知未启用或 SMTP 配置不完整",
        )
        if any(marker in setting.last_error for marker in incomplete_config_markers):
            setting.last_error = None
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


@router.get("/notification-recipients", response_model=list[NotificationRecipientResponse])
def list_recipients(db: Session = Depends(get_db)):
    return list(db.scalars(select(NotificationRecipient).order_by(NotificationRecipient.created_at.asc())).all())


@router.post("/notification-recipients", response_model=NotificationRecipientResponse, status_code=201)
def create_recipient(payload: NotificationRecipientCreate, db: Session = Depends(get_db)):
    recipient = NotificationRecipient(**payload.model_dump())
    db.add(recipient)
    db.commit()
    db.refresh(recipient)
    return recipient


@router.patch("/notification-recipients/{recipient_id}", response_model=NotificationRecipientResponse)
def update_recipient(
    recipient_id: int,
    payload: NotificationRecipientUpdate,
    db: Session = Depends(get_db),
):
    recipient = db.get(NotificationRecipient, recipient_id)
    if recipient is None:
        raise HTTPException(status_code=404, detail="Recipient not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(recipient, field, value)
    db.add(recipient)
    db.commit()
    db.refresh(recipient)
    return recipient


@router.delete("/notification-recipients/{recipient_id}")
def delete_recipient(recipient_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    recipient = db.get(NotificationRecipient, recipient_id)
    if recipient is None:
        raise HTTPException(status_code=404, detail="Recipient not found")
    db.delete(recipient)
    db.commit()
    return {"ok": True}


@router.post("/notification-recipients/{recipient_id}/test")
def test_recipient(recipient_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    recipient = db.get(NotificationRecipient, recipient_id)
    if recipient is None:
        raise HTTPException(status_code=404, detail="Recipient not found")
    try:
        send_test_email(db, recipient)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}
