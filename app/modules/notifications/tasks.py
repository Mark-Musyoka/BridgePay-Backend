import logging

from celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.modules.notifications.tasks.send_notification_email")
def send_notification_email(to_email: str, title: str, body: str) -> dict:
    """Mocked — same pattern as every other email task in this codebase
    (auth verification/reset, transfer confirmation). Logs instead of
    actually sending."""
    logger.info("Notification email to %s — %s: %s", to_email, title, body)
    return {"to_email": to_email, "sent": True}
