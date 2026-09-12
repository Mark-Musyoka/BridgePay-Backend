import json

from app.core.airtel_client import verify_callback_signature as verify_airtel_signature
from app.core.config import settings
from app.core.stripe_client import stripe
from app.modules.deposits.service import (
    handle_airtel_collection_callback,
    handle_mpesa_stk_callback,
    handle_stripe_webhook_event,
)
from app.modules.payouts.service import (
    handle_airtel_disbursement_callback,
    handle_mpesa_b2c_result,
    handle_stripe_payout_failed_event,
)
from sqlalchemy.ext.asyncio import AsyncSession


class InvalidWebhookSignature(Exception):
    pass


async def verify_and_dispatch_stripe_event(db: AsyncSession, *, payload: bytes, signature: str | None) -> None:
    """
    Verifies the Stripe signature — the one thing standing between "only
    Stripe can trigger a deposit or reverse a payout" and "anyone who
    finds this URL can credit or manipulate any account" — then routes
    the event to whichever module actually owns handling it. Webhooks
    itself never touches a Deposit or Payout row directly; it's a
    dispatcher, not a state owner.
    """
    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise InvalidWebhookSignature("Invalid webhook signature")

    event_type = event.get("type")
    if event_type == "payout.failed":
        await handle_stripe_payout_failed_event(db, event)
    else:
        await handle_stripe_webhook_event(db, event)


async def dispatch_mpesa_stk_callback(db: AsyncSession, payload: dict) -> None:
    await handle_mpesa_stk_callback(db, payload)


async def dispatch_mpesa_b2c_result(db: AsyncSession, payload: dict) -> None:
    await handle_mpesa_b2c_result(db, payload)


async def _verify_airtel_or_raise(raw_body: bytes, signature: str | None) -> None:
    """Shared by both Airtel callback endpoints — unlike M-Pesa's Daraja
    (which signs nothing at all), Airtel callbacks ARE expected to carry
    a signature, so an invalid/missing one is rejected outright rather
    than merely noted as a caveat. See airtel_client.py's module
    docstring for what this actually checks and its confidence level."""
    if not verify_airtel_signature(raw_body, signature):
        raise InvalidWebhookSignature("Invalid or missing Airtel callback signature")


async def dispatch_airtel_collection_callback(db: AsyncSession, *, raw_body: bytes, signature: str | None) -> None:
    await _verify_airtel_or_raise(raw_body, signature)
    payload = json.loads(raw_body)
    await handle_airtel_collection_callback(db, payload)


async def dispatch_airtel_disbursement_callback(db: AsyncSession, *, raw_body: bytes, signature: str | None) -> None:
    await _verify_airtel_or_raise(raw_body, signature)
    payload = json.loads(raw_body)
    await handle_airtel_disbursement_callback(db, payload)
