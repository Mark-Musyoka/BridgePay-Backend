import asyncio
import logging

from celery_app import celery_app
from app.core.email import is_configured, send_email

logger = logging.getLogger(__name__)


@celery_app.task(name="app.modules.notifications.tasks.send_notification_email")
def send_notification_email(to_email: str, title: str, body: str) -> dict:
    """
    Sends a real email via SMTP when configured (see core/email.py);
    otherwise falls back to the original mocked (log-only) behavior —
    same pattern as every other email task in this codebase. title/body
    are already the exact text shown in-app (see notify() in
    notifications/service.py), reused as-is here rather than composing
    separate copy for the email.
    """
    logger.info("Notification email to %s — %s: %s", to_email, title, body)

    sent = True
    if is_configured():
        html_body = f"<p>{body}</p>"
        sent = asyncio.run(send_email(to=to_email, subject=title, html_body=html_body, text_body=body))

    return {"to_email": to_email, "sent": sent}
