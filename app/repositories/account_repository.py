import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account


class AccountRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(self, user_id: uuid.UUID) -> Account | None:
        result = await self.db.execute(select(Account).where(Account.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_by_id_locked(self, account_id: uuid.UUID) -> Account:
        """SELECT ... FOR UPDATE — caller is responsible for lock ordering
        (see transfer_service.py, which locks by ascending account id)."""
        result = await self.db.execute(select(Account).where(Account.id == account_id).with_for_update())
        return result.scalar_one()

    async def create(self, *, user_id: uuid.UUID, balance: Decimal = Decimal("0.00")) -> Account:
        account = Account(user_id=user_id, balance=balance)
        self.db.add(account)
        await self.db.flush()
        return account
