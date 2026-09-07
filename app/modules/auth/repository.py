import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import EmailVerificationToken, OAuthHandoffCode, PasswordResetToken, RefreshToken


class RefreshTokenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self.db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        return result.scalar_one_or_none()

    async def create(self, *, user_id: uuid.UUID, token_hash: str, expires_at) -> RefreshToken:
        token = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self.db.add(token)
        await self.db.flush()
        return token


class EmailVerificationTokenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_hash(self, token_hash: str) -> EmailVerificationToken | None:
        result = await self.db.execute(
            select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def create(self, *, user_id: uuid.UUID, token_hash: str, expires_at) -> EmailVerificationToken:
        token = EmailVerificationToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self.db.add(token)
        await self.db.flush()
        return token


class PasswordResetTokenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        result = await self.db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def create(self, *, user_id: uuid.UUID, token_hash: str, expires_at) -> PasswordResetToken:
        token = PasswordResetToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self.db.add(token)
        await self.db.flush()
        return token


class OAuthHandoffCodeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_hash(self, code_hash: str) -> OAuthHandoffCode | None:
        result = await self.db.execute(
            select(OAuthHandoffCode).where(OAuthHandoffCode.code_hash == code_hash)
        )
        return result.scalar_one_or_none()

    async def create(self, *, user_id: uuid.UUID, code_hash: str, expires_at) -> OAuthHandoffCode:
        code = OAuthHandoffCode(user_id=user_id, code_hash=code_hash, expires_at=expires_at)
        self.db.add(code)
        await self.db.flush()
        return code
