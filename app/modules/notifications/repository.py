import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification, NotificationType


class NotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self, *, user_id: uuid.UUID, type: NotificationType, title: str, body: str
    ) -> Notification:
        notification = Notification(user_id=user_id, type=type, title=title, body=body)
        self.db.add(notification)
        await self.db.flush()
        return notification

    async def list_for_user(self, user_id: uuid.UUID, *, page: int, page_size: int, unread_only: bool = False):
        condition = Notification.user_id == user_id
        query = select(Notification).where(condition)
        count_query = select(func.count()).select_from(Notification).where(condition)

        if unread_only:
            query = query.where(Notification.is_read == False)  # noqa: E712
            count_query = count_query.where(Notification.is_read == False)  # noqa: E712

        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        items_result = await self.db.execute(
            query.order_by(Notification.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        items = items_result.scalars().all()
        return items, total

    async def get_by_id_for_user(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification | None:
        result = await self.db.execute(
            select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def mark_all_read(self, user_id: uuid.UUID) -> None:
        await self.db.execute(
            update(Notification).where(Notification.user_id == user_id).values(is_read=True)
        )
        await self.db.flush()
