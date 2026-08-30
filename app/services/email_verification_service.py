from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_refresh_token, hash_refresh_token
from app.repositories.email_verification_token_repository import EmailVerificationTokenRepository
from app.repositories.user_repository import UserRepository

VERIFICATION_TOKEN_EXPIRE_HOURS = 24


class EmailVerificationTokenInvalid(Exception):
    pass


async def issue_verification_token(db: AsyncSession, user_id) -> str:
    # Reuses the same high-entropy token generator/hasher as refresh tokens —
    # the security property needed (unguessable, safe to hash-and-store) is
    # identical, no reason for a second implementation.
    raw_token = generate_refresh_token()
    await EmailVerificationTokenRepository(db).create(
        user_id=user_id,
        token_hash=hash_refresh_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=VERIFICATION_TOKEN_EXPIRE_HOURS),
    )
    return raw_token


async def confirm_verification_token(db: AsyncSession, raw_token: str) -> None:
    token_hash = hash_refresh_token(raw_token)
    token_repo = EmailVerificationTokenRepository(db)
    stored = await token_repo.get_by_hash(token_hash)

    if stored is None or stored.used or stored.expires_at < datetime.now(timezone.utc):
        raise EmailVerificationTokenInvalid("Invalid or expired verification token")

    stored.used = True

    user = await UserRepository(db).get_by_id(stored.user_id)
    user.is_verified = True
