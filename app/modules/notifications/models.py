import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationType(str, enum.Enum):
    transfer_sent = "transfer_sent"
    transfer_received = "transfer_received"
    deposit_completed = "deposit_completed"
    deposit_failed = "deposit_failed"
    payout_sent = "payout_sent"
    payout_failed = "payout_failed"
    payout_reversed = "payout_reversed"
    security_alert = "security_alert"
    account_update = "account_update"


class Notification(Base):
    """
    In-app notification, always created regardless of whether an email
    is also sent — the notification bell/list is the source of truth a
    user can always check, independent of whether the (mocked) email
    "arrived". See app/modules/notifications/service.py for the create
    helper every other module calls into.
    """
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
