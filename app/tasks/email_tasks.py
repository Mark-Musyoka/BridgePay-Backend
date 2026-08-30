import logging

from celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.email_tasks.send_verification_email")
def send_verification_email(to_email: str, raw_token: str) -> dict:
    """
    Mocked — in a real system this would send an actual email with a link
    like https://bridgepay.app/verify-email?token=<raw_token>. For now it
    just logs, matching the pattern in transfer_tasks.py. The raw token only
    ever exists here (in the "email") and in the request/response cycle
    that issued it — it's never stored anywhere in plaintext.
    """
    logger.info("Verification email to %s — token: %s", to_email, raw_token)
    return {"to_email": to_email, "sent": True}


@celery_app.task(name="app.tasks.email_tasks.send_password_reset_email")
def send_password_reset_email(to_email: str, raw_token: str) -> dict:
    """Mocked, same pattern as send_verification_email above."""
    logger.info("Password reset email to %s — token: %s", to_email, raw_token)
    return {"to_email": to_email, "sent": True}
