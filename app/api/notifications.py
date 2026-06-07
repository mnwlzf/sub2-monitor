from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import encrypt_secret
from app.schemas.notification import NotificationSettingResponse, NotificationSettingUpdate
from app.services.notification import get_notification_setting, send_test_email

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
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


@router.post("/notification-settings/test")
def test_settings(db: Session = Depends(get_db)) -> dict[str, bool]:
    try:
        send_test_email(db)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}
