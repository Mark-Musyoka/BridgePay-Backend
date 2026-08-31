import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.transactions.models import Transaction


class TransactionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_account(self, account_id: uuid.UUID, *, page: int, page_size: int):
        account_filter = or_(
            Transaction.from_account_id == account_id,
            Transaction.to_account_id == account_id,
        )
        return await self._list_and_count(account_filter, page=page, page_size=page_size)

    async def list_all(self, *, page: int, page_size: int, account_id: uuid.UUID | None = None):
        account_filter = None
        if account_id is not None:
            account_filter = or_(
                Transaction.from_account_id == account_id,
                Transaction.to_account_id == account_id,
            )
        return await self._list_and_count(account_filter, page=page, page_size=page_size)

    async def _list_and_count(self, condition, *, page: int, page_size: int):
        query = select(Transaction)
        count_query = select(func.count()).select_from(Transaction)
        if condition is not None:
            query = query.where(condition)
            count_query = count_query.where(condition)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        items_result = await self.db.execute(
            query.order_by(Transaction.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        items = items_result.scalars().all()
        return items, total
