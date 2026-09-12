import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payouts.models import Payout, PayoutProvider, PayoutStatus


class PayoutRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        provider: PayoutProvider,
        destination_reference: str,
        recipient_email: str,
        amount,
        currency: str,
        external_reference: str | None = None,
        idempotency_key: str | None = None,
        exchange_rate=None,
        converted_amount=None,
    ) -> Payout:
        payout = Payout(
            user_id=user_id,
            account_id=account_id,
            provider=provider,
            destination_reference=destination_reference,
            recipient_email=recipient_email,
            amount=amount,
            currency=currency,
            external_reference=external_reference,
            idempotency_key=idempotency_key,
            exchange_rate=exchange_rate,
            converted_amount=converted_amount,
        )
        self.db.add(payout)
        await self.db.flush()
        return payout

    async def set_conversion(self, payout: Payout, *, exchange_rate, converted_amount) -> None:
        """Records the rate applied and the resulting account-currency
        amount at the point the payout's balance deduction actually
        happens — see _deduct_balance_and_record in service.py. Left
        unset (both stay NULL) when the payout's currency already
        matches the account's."""
        payout.exchange_rate = exchange_rate
        payout.converted_amount = converted_amount
        await self.db.flush()

    async def get_by_external_reference(self, external_reference: str) -> Payout | None:
        result = await self.db.execute(select(Payout).where(Payout.external_reference == external_reference))
        return result.scalar_one_or_none()

    async def get_by_idempotency_key_for_user(self, user_id: uuid.UUID, idempotency_key: str) -> Payout | None:
        result = await self.db.execute(
            select(Payout).where(Payout.user_id == user_id, Payout.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID, *, page: int, page_size: int):
        query = select(Payout).where(Payout.user_id == user_id)
        count_query = select(func.count()).select_from(Payout).where(Payout.user_id == user_id)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        items_result = await self.db.execute(
            query.order_by(Payout.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        items = items_result.scalars().all()
        return items, total

    async def set_external_reference(self, payout: Payout, external_reference: str) -> None:
        payout.external_reference = external_reference
        await self.db.flush()

    async def mark_completed(self, payout: Payout) -> None:
        payout.status = PayoutStatus.completed
        payout.completed_at = datetime.now(timezone.utc)
        await self.db.flush()

    async def mark_failed(self, payout: Payout, *, reason: str) -> None:
        payout.status = PayoutStatus.failed
        payout.failure_reason = reason
        await self.db.flush()

    async def mark_reversed(self, payout: Payout, *, reason: str) -> None:
        payout.status = PayoutStatus.reversed
        payout.failure_reason = reason
        await self.db.flush()
