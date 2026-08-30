import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_verification_token import EmailVerificationToken


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
