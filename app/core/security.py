import hashlib
import hmac
import secrets
from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet

from app.core.config import get_settings

password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def new_token(byte_count: int = 32) -> str:
    return secrets.token_urlsafe(byte_count)


def hash_token(token: str) -> str:
    secret = get_settings().secret_key.encode("utf-8")
    digest = hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def _fernet() -> Fernet:
    key_material = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
    return Fernet(urlsafe_b64encode(key_material))


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def expires_at(seconds: int) -> datetime:
    return utcnow() + timedelta(seconds=seconds)
