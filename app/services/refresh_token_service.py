from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import generate_refresh_token, hash_refresh_token
from app.models.refresh_token import RefreshToken


class RefreshTokenReused(Exception):
    """Raised when an already-used (revoked) refresh token is presented again —
    a signal of possible theft."""
    pass


class RefreshTokenInvalid(Exception):
    pass


async def issue_refresh_token(db: AsyncSession, user_id) -> str:
    raw_token = generate_refresh_token()
    token = RefreshToken(
        user_id=user_id,
        token_hash=hash_refresh_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(token)
    await db.flush()
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
    token_hash = hash_refresh_token(raw_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    stored = result.scalar_one_or_none()

    if stored is None:
        raise RefreshTokenInvalid("Unknown refresh token")

    if stored.revoked:
        # Reuse of a revoked token — nuke every token for this user as a precaution.
        await db.execute(
            update(RefreshToken).where(RefreshToken.user_id == stored.user_id).values(revoked=True)
        )
        await db.flush()
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
