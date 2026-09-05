import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payment_methods.models import PaymentMethod, PaymentMethodProvider


class PaymentMethodRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_user(self, user_id: uuid.UUID) -> list[PaymentMethod]:
        result = await self.db.execute(
            select(PaymentMethod).where(PaymentMethod.user_id == user_id).order_by(PaymentMethod.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id_for_user(self, method_id: uuid.UUID, user_id: uuid.UUID) -> PaymentMethod | None:
        result = await self.db.execute(
            select(PaymentMethod).where(PaymentMethod.id == method_id, PaymentMethod.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_default_for_user(
        self, user_id: uuid.UUID, provider: PaymentMethodProvider | None = None
    ) -> PaymentMethod | None:
        query = select(PaymentMethod).where(PaymentMethod.user_id == user_id, PaymentMethod.is_default == True)  # noqa: E712
        if provider is not None:
            query = query.where(PaymentMethod.provider == provider)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        provider: PaymentMethodProvider,
        type,
        external_reference: str,
        masked_details: str,
        is_default: bool = False,
    ) -> PaymentMethod:
        method = PaymentMethod(
            user_id=user_id,
            provider=provider,
            type=type,
            external_reference=external_reference,
            masked_details=masked_details,
            is_default=is_default,
        )
        self.db.add(method)
        await self.db.flush()
        return method

    async def unset_default_for_user(self, user_id: uuid.UUID) -> None:
        await self.db.execute(
            update(PaymentMethod).where(PaymentMethod.user_id == user_id).values(is_default=False)
        )
        await self.db.flush()

    async def delete(self, method: PaymentMethod) -> None:
        await self.db.delete(method)
        await self.db.flush()
