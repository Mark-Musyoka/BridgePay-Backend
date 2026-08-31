"""Business logic for tokens: refresh (session) rotation, email
verification, and password reset. Kept in one file since all three are
small and share the same underlying token generate/hash pattern from
app.core.security — splitting them into separate files would mostly
duplicate that shared context for no real benefit at this size."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
)
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import (
    EmailVerificationTokenRepository,
    PasswordResetTokenRepository,
    RefreshTokenRepository,
)
from app.modules.users.repository import UserRepository

VERIFICATION_TOKEN_EXPIRE_HOURS = 24
RESET_TOKEN_EXPIRE_MINUTES = 30


class RefreshTokenReused(Exception):
    """Raised when an already-used (revoked) refresh token is presented
    again — a signal of possible theft."""
    pass


class RefreshTokenInvalid(Exception):
    pass


class EmailVerificationTokenInvalid(Exception):
    pass


class PasswordResetTokenInvalid(Exception):
    pass


# --- Refresh tokens (sessions) ---------------------------------------------

async def issue_refresh_token(db: AsyncSession, user_id) -> str:
    raw_token = generate_refresh_token()
    await RefreshTokenRepository(db).create(
        user_id=user_id,
        token_hash=hash_refresh_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    return raw_token


async def rotate_refresh_token(db: AsyncSession, raw_token: str) -> tuple[str, str]:
    """
    Validate raw_token, then rotate it: revoke the old one and issue a new one.
    Returns (user_id_str, new_raw_refresh_token).

    Reuse detection: if the presented token's hash matches a row that's
    already revoked, someone is replaying a used-up token — most likely
    because the original was stolen and both the thief and the legitimate
    user have now used it. We respond by revoking every refresh token for
    that user, forcing re-login everywhere.
    """
    token_repo = RefreshTokenRepository(db)
    token_hash = hash_refresh_token(raw_token)
    stored = await token_repo.get_by_hash(token_hash)

    if stored is None:
        raise RefreshTokenInvalid("Unknown refresh token")

    if stored.revoked:
        await revoke_all_for_user(db, stored.user_id)
        raise RefreshTokenReused("Refresh token reuse detected")

    if stored.expires_at < datetime.now(timezone.utc):
        raise RefreshTokenInvalid("Refresh token expired")

    stored.revoked = True
    new_raw_token = await issue_refresh_token(db, stored.user_id)

    return str(stored.user_id), new_raw_token


async def revoke_all_for_user(db: AsyncSession, user_id) -> None:
    await db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id).values(revoked=True))
    await db.flush()


async def revoke_refresh_token(db: AsyncSession, raw_token: str) -> None:
    token_hash = hash_refresh_token(raw_token)
    await db.execute(update(RefreshToken).where(RefreshToken.token_hash == token_hash).values(revoked=True))
    await db.flush()


# --- Email verification -----------------------------------------------------

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
    stored = await EmailVerificationTokenRepository(db).get_by_hash(token_hash)

    if stored is None or stored.used or stored.expires_at < datetime.now(timezone.utc):
        raise EmailVerificationTokenInvalid("Invalid or expired verification token")

    stored.used = True

    user = await UserRepository(db).get_by_id(stored.user_id)
    user.is_verified = True


# --- Password reset ----------------------------------------------------------

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
    stored = await PasswordResetTokenRepository(db).get_by_hash(token_hash)

    if stored is None or stored.used or stored.expires_at < datetime.now(timezone.utc):
        raise PasswordResetTokenInvalid("Invalid or expired reset token")

    stored.used = True

    user = await UserRepository(db).get_by_id(stored.user_id)
    user.hashed_password = hash_password(new_password)

    # A password reset is a strong signal the account may have been at
    # risk — kill every existing session (refresh token) so a stolen
    # session doesn't survive the password change.
    await revoke_all_for_user(db, user.id)
