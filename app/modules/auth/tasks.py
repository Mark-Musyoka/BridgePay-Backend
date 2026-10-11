import asyncio
import logging

from celery_app import celery_app
from app.core.config import settings
from app.core.email import is_configured, send_email

logger = logging.getLogger(__name__)


@celery_app.task(name="app.modules.auth.tasks.send_verification_email")
def send_verification_email(to_email: str, raw_token: str) -> dict:
    """
    Sends a real email via SMTP when configured (see core/email.py's
    is_configured()); otherwise falls back to the original mocked
    (log-only) behavior, so local dev without SMTP credentials still
    works exactly as before. The link is logged either way — the
    console is also how you'd grab it to test the verify-email flow
    without real email.
    """
    verify_url = f"{settings.FRONTEND_BASE_URL}/verify-email?token={raw_token}"
    logger.info("Verification email to %s — link: %s", to_email, verify_url)

    sent = True
    if is_configured():
        html_body = f"""
        <p>Welcome to BridgePay — confirm your email to get started.</p>
        <p><a href="{verify_url}">Verify your email</a></p>
        <p>Or paste this link into your browser:<br>{verify_url}</p>
        <p style="color:#666;font-size:13px">If you didn't create a BridgePay account, you can ignore this email.</p>
        """
        text_body = (
            f"Welcome to BridgePay — confirm your email to get started.\n\n"
            f"Verify your email: {verify_url}\n\n"
            f"If you didn't create a BridgePay account, you can ignore this email."
        )
        sent = asyncio.run(
            send_email(to=to_email, subject="Verify your BridgePay email", html_body=html_body, text_body=text_body)
        )

    return {"to_email": to_email, "sent": sent}


@celery_app.task(name="app.modules.auth.tasks.send_password_reset_email")
def send_password_reset_email(to_email: str, raw_token: str) -> dict:
    """Same pattern as send_verification_email above."""
    reset_url = f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw_token}"
    logger.info("Password reset email to %s — link: %s", to_email, reset_url)

    sent = True
    if is_configured():
        html_body = f"""
        <p>We received a request to reset your BridgePay password.</p>
        <p><a href="{reset_url}">Reset your password</a></p>
        <p>Or paste this link into your browser:<br>{reset_url}</p>
        <p style="color:#666;font-size:13px">If you didn't request this, you can ignore this email — your password won't change.</p>
        """
        text_body = (
            f"We received a request to reset your BridgePay password.\n\n"
            f"Reset your password: {reset_url}\n\n"
            f"If you didn't request this, you can ignore this email — your password won't change."
        )
        sent = asyncio.run(
            send_email(to=to_email, subject="Reset your BridgePay password", html_body=html_body, text_body=text_body)
        )

    return {"to_email": to_email, "sent": sent}
