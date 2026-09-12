import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deposits.models import Deposit, DepositProvider, DepositStatus


class DepositRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        provider: DepositProvider,
        amount,
        currency: str,
        external_reference: str,
        idempotency_key: str | None = None,
        exchange_rate=None,
        converted_amount=None,
    ) -> Deposit:
        deposit = Deposit(
            user_id=user_id,
            account_id=account_id,
            provider=provider,
            amount=amount,
            currency=currency,
            external_reference=external_reference,
            idempotency_key=idempotency_key,
            exchange_rate=exchange_rate,
            converted_amount=converted_amount,
        )
        self.db.add(deposit)
        await self.db.flush()
        return deposit

    async def get_by_external_reference(self, external_reference: str) -> Deposit | None:
        result = await self.db.execute(select(Deposit).where(Deposit.external_reference == external_reference))
        return result.scalar_one_or_none()

    async def get_by_idempotency_key_for_user(self, user_id: uuid.UUID, idempotency_key: str) -> Deposit | None:
        result = await self.db.execute(
            select(Deposit).where(Deposit.user_id == user_id, Deposit.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID, *, page: int, page_size: int):
        query = select(Deposit).where(Deposit.user_id == user_id)
        count_query = select(func.count()).select_from(Deposit).where(Deposit.user_id == user_id)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        items_result = await self.db.execute(
            query.order_by(Deposit.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        items = items_result.scalars().all()
        return items, total

    async def set_conversion(self, deposit: Deposit, *, exchange_rate, converted_amount) -> None:
        """Records the rate applied and the resulting account-currency
        amount at the point the deposit is actually credited — see
        _credit_account_and_record in service.py. Left unset (both stay
        NULL) when the deposit's currency already matches the account's."""
        deposit.exchange_rate = exchange_rate
        deposit.converted_amount = converted_amount
        await self.db.flush()

    async def mark_completed(self, deposit: Deposit) -> None:
        deposit.status = DepositStatus.completed
        deposit.completed_at = datetime.now(timezone.utc)
        await self.db.flush()

    async def mark_failed(self, deposit: Deposit, *, reason: str) -> None:
        deposit.status = DepositStatus.failed
        deposit.failure_reason = reason
        await self.db.flush()
