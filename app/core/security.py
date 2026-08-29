from datetime import datetime, timedelta, timezone
import hashlib
import secrets

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


def hash_password(plain_password: str) -> str:
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Create a JWT for the given subject (typically the user's id as a string)."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode = {"sub": subject, "exp": expire}
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Decode a JWT and return the subject (user id), or None if invalid/expired."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def generate_refresh_token() -> str:
    """A high-entropy random string — not a JWT, since we look it up (hashed) in the DB."""
    return secrets.token_urlsafe(64)


def hash_refresh_token(raw_token: str) -> str:
    """SHA-256 is fine here (unlike passwords): the input is already high-entropy
    random data, not something an attacker could feasibly guess or brute-force —
    we're hashing for lookup/storage safety, not for resisting guessing attacks."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
