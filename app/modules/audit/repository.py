from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog


class AuditLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self, *, page: int, page_size: int, action: str | None = None):
        query = select(AuditLog)
        count_query = select(func.count()).select_from(AuditLog)
        if action:
            query = query.where(AuditLog.action == action)
            count_query = count_query.where(AuditLog.action == action)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        items_result = await self.db.execute(
            query.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        items = items_result.scalars().all()
        return items, total
