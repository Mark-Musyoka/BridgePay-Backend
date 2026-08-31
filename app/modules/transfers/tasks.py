import logging

from celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.modules.transfers.tasks.send_transfer_confirmation")
def send_transfer_confirmation(
    transaction_id: str,
    from_email: str,
    to_email: str,
    amount: str,
) -> dict:
    """
    Mocked notification task — in a real system this would send an email
    or push notification. For now it just logs, so we can prove the
    async pipeline (API -> Celery -> worker) actually works end-to-end.
    """
    logger.info(
        "Transfer confirmation: %s sent %s to %s (transaction %s)",
        from_email,
        amount,
        to_email,
        transaction_id,
    )
    return {
        "transaction_id": transaction_id,
        "from_email": from_email,
        "to_email": to_email,
        "amount": amount,
        "notified": True,
    }
