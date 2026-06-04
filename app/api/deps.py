from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.session import AuthSession
from app.models.user import User
from app.services.auth import get_session_by_token


def current_session(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthSession:
    token = request.cookies.get(settings.session_cookie_name)
    session = get_session_by_token(db, token)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return session


def current_user(session: AuthSession = Depends(current_session)) -> User:
    if not session.user or not session.user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return session.user


def verify_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None),
    csrf_cookie: str | None = Cookie(default=None, alias="sub2_monitor_csrf"),
    session: AuthSession = Depends(current_session),
) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if not x_csrf_token or not csrf_cookie:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF token")
    if x_csrf_token != csrf_cookie or x_csrf_token != session.csrf_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")

