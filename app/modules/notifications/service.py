from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import NotificationType
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.tasks import send_notification_email


async def notify(
    db: AsyncSession,
    *,
    user_id,
    user_email: str,
    type: NotificationType,
    title: str,
    body: str,
) -> None:
    """
    Single entry point every other module calls to raise a notification —
    always creates the in-app row (the source of truth), and always
    queues the mocked email alongside it. Callers don't need to know or
    care about the email side; this function owns that.

    Uses flush (not commit) — same reasoning as everywhere else in this
    codebase: the caller commits, so this notification lands in the same
    atomic DB transaction as whatever triggered it (a transfer, a
    deposit, etc.), rather than being a separate, potentially
    inconsistent write.
    """
    await NotificationRepository(db).create(user_id=user_id, type=type, title=title, body=body)

    try:
        send_notification_email.delay(to_email=user_email, title=title, body=body)
    except Exception:
        # Same non-blocking pattern as every other Celery call site in
        # this codebase — the in-app notification (the source of truth)
        # has already been created; a broker outage shouldn't roll that
        # back or fail the caller's whole request.
        pass
