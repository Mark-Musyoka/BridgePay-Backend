import asyncio
import logging

from celery_app import celery_app
from app.core.email import is_configured, send_email

logger = logging.getLogger(__name__)


@celery_app.task(name="app.modules.transfers.tasks.send_transfer_confirmation")
def send_transfer_confirmation(
    transaction_id: str,
    from_email: str,
    to_email: str,
    amount: str,
) -> dict:
    """
    Sends a real receipt-style confirmation to the sender via SMTP when
    configured; otherwise falls back to the original mocked (log-only)
    behavior. Addressed to from_email (the person who initiated the
    transfer) — the recipient's own "money received" notification is
    handled separately by notify()/send_notification_email, not this
    task.
    """
    logger.info(
        "Transfer confirmation: %s sent %s to %s (transaction %s)",
        from_email,
        amount,
        to_email,
        transaction_id,
    )

    sent = True
    if is_configured():
        html_body = (
            f"<p>You sent {amount} to {to_email}.</p>"
            f"<p style='color:#666;font-size:13px'>Transaction ID: {transaction_id}</p>"
        )
        text_body = f"You sent {amount} to {to_email}.\n\nTransaction ID: {transaction_id}"
        sent = asyncio.run(
            send_email(to=from_email, subject="Transfer confirmation", html_body=html_body, text_body=text_body)
        )

    return {
        "transaction_id": transaction_id,
        "from_email": from_email,
        "to_email": to_email,
        "amount": amount,
        "notified": sent,
    }
