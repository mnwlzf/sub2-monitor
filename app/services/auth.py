from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import expires_at, hash_password, hash_token, new_token, utcnow, verify_password
from app.models.session import AuthSession
from app.models.user import User


def bootstrap_first_user(db: Session, settings: Settings) -> None:
    existing = db.scalar(select(User.id).limit(1))
    if existing:
        return
    if settings.is_production and (
        settings.secret_key == "dev-only-change-me"
        or settings.bootstrap_password == "change-this-password"
    ):
        raise RuntimeError("Production requires a strong SECRET_KEY and bootstrap password.")
    user = User(
        username=settings.bootstrap_username,
        password_hash=hash_password(settings.bootstrap_password),
    )
    db.add(user)
    db.commit()


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username, User.is_active.is_(True)))
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def create_session(
    db: Session,
    user: User,
    settings: Settings,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[str, AuthSession]:
    raw_token = new_token()
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        csrf_token=new_token(24),
        expires_at=expires_at(settings.session_ttl_seconds),
        user_agent=user_agent[:255] if user_agent else None,
        ip_address=ip_address,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return raw_token, session


def get_session_by_token(db: Session, token: str | None) -> AuthSession | None:
    if not token:
        return None
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is None:
        return None
    if session.expires_at <= utcnow():
        db.delete(session)
        db.commit()
        return None
    return session


def delete_session(db: Session, token: str | None) -> None:
    if not token:
        return
    db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    db.commit()


def delete_expired_sessions(db: Session) -> None:
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= utcnow()))
    db.commit()

