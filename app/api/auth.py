from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import current_session, current_user, verify_csrf
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import new_token
from app.models.session import AuthSession
from app.models.user import User
from app.schemas.auth import CsrfResponse, LoginRequest, SessionResponse, UserResponse
from app.services.auth import authenticate_user, create_session, delete_session

router = APIRouter(prefix="/auth", tags=["auth"])


def set_auth_cookies(response: Response, settings: Settings, token: str, csrf_token: str) -> None:
    secure_cookie = settings.is_production
    max_age = settings.session_ttl_seconds
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        max_age=max_age,
        path="/",
    )
    response.set_cookie(
        key="sub2_monitor_csrf",
        value=csrf_token,
        httponly=False,
        secure=secure_cookie,
        samesite="lax",
        max_age=max_age,
        path="/",
    )


@router.get("/csrf", response_model=CsrfResponse)
def csrf_token(response: Response, settings: Settings = Depends(get_settings)) -> CsrfResponse:
    token = new_token(24)
    response.set_cookie(
        key="sub2_monitor_login_csrf",
        value=token,
        httponly=False,
        secure=settings.is_production,
        samesite="lax",
        max_age=600,
        path="/",
    )
    return CsrfResponse(csrf_token=token)


@router.post("/login", response_model=SessionResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    x_csrf_token: str | None = Header(default=None),
    login_csrf_cookie: str | None = Cookie(default=None, alias="sub2_monitor_login_csrf"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SessionResponse:
    if not x_csrf_token or not login_csrf_cookie or x_csrf_token != login_csrf_cookie:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    user = authenticate_user(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token, session = create_session(
        db,
        user,
        settings,
        request.headers.get("user-agent"),
        request.client.host if request.client else None,
    )
    set_auth_cookies(response, settings, token, session.csrf_token)
    response.delete_cookie("sub2_monitor_login_csrf", path="/")
    return SessionResponse(
        user=UserResponse(id=user.id, username=user.username),
        csrf_token=session.csrf_token,
    )


@router.get("/me", response_model=SessionResponse)
def me(user: User = Depends(current_user), session: AuthSession = Depends(current_session)) -> SessionResponse:
    return SessionResponse(
        user=UserResponse(id=user.id, username=user.username),
        csrf_token=session.csrf_token,
    )


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    delete_session(db, request.cookies.get(settings.session_cookie_name))
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie("sub2_monitor_csrf", path="/")
    return {"ok": True}
