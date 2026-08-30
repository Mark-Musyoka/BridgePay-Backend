from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_refresh_token, hash_password, hash_refresh_token
from app.repositories.password_reset_token_repository import PasswordResetTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.refresh_token_service import revoke_all_for_user

RESET_TOKEN_EXPIRE_MINUTES = 30


class PasswordResetTokenInvalid(Exception):
    pass


async def request_password_reset(db: AsyncSession, email: str) -> str | None:
    """
    Returns the raw token to email if the user exists, or None if they
    don't — the caller (route) must respond identically either way, so an
    attacker can't use this endpoint to discover which emails are
    registered.
    """
    user = await UserRepository(db).get_by_email(email)
    if user is None:
        return None

    raw_token = generate_refresh_token()
    await PasswordResetTokenRepository(db).create(
        user_id=user.id,
        token_hash=hash_refresh_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
    )
    return raw_token


async def confirm_password_reset(db: AsyncSession, raw_token: str, new_password: str) -> None:
    token_hash = hash_refresh_token(raw_token)
    token_repo = PasswordResetTokenRepository(db)
    stored = await token_repo.get_by_hash(token_hash)

    if stored is None or stored.used or stored.expires_at < datetime.now(timezone.utc):
        raise PasswordResetTokenInvalid("Invalid or expired reset token")

    stored.used = True

    user = await UserRepository(db).get_by_id(stored.user_id)
    user.hashed_password = hash_password(new_password)

    # A password reset is a strong signal the account may have been at
    # risk — kill every existing session (refresh token) so a stolen
    # session doesn't survive the password change.
    await revoke_all_for_user(db, user.id)
