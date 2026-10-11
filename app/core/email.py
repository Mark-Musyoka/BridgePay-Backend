"""
Real email sending over SMTP (aiosmtplib) — works with any provider,
including Resend's SMTP relay (see config.py's SMTP_* settings for
Resend-specific values).

send_email() is used by the email-sending Celery tasks (auth, transfers,
notifications — grep for "from app.core.email import send_email"). When
SMTP_HOST isn't configured, is_configured() is False and those tasks
fall back to their original mocked (log-only) behavior instead of
calling this at all — same resilience philosophy as the rate limiter's
swallow_errors (Phase 17): an unconfigured or failing email provider
should never be what breaks registration, a password reset, or a
transfer.
"""

import logging

import aiosmtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_USERNAME and settings.SMTP_PASSWORD)


async def send_email(*, to: str, subject: str, html_body: str, text_body: str) -> bool:
    """
    Sends one email. Returns True on success, False on any failure —
    never raises. Callers (the Celery tasks) decide what "failure"
    means for them; for every email this codebase sends so far (auth
    links, transfer/payout confirmations) a failed send is logged and
    otherwise swallowed, matching the existing mocked behavior's
    fire-and-forget shape rather than retrying or failing the task.

    text_body is required, not optional — some mail clients and most
    spam filters penalize HTML-only email, so every call site should
    have a plain-text equivalent of its HTML, not just an afterthought.
    """
    if not is_configured():
        logger.warning("send_email called but SMTP is not configured — dropping email to %s", to)
        return False

    message = EmailMessage()
    message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            # 465 is implicit TLS (the whole connection is encrypted from
            # the start); 587/others use STARTTLS (plain connection that
            # upgrades to TLS). aiosmtplib needs to know which up front.
            use_tls=settings.SMTP_PORT == 465,
            start_tls=settings.SMTP_PORT != 465,
        )
        return True
    except Exception:
        logger.exception("Failed to send email to %s (subject: %r)", to, subject)
        return False
