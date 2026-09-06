import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.stripe_client import stripe
from app.db.session import get_db
from app.modules.deposits.service import handle_mpesa_stk_callback, handle_stripe_webhook_event
from app.modules.payouts.service import handle_mpesa_b2c_result, handle_stripe_payout_failed_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    signature = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        # Always reject unsigned/invalid-signature requests — this is the
        # one thing standing between "only Stripe can trigger a deposit
        # or reverse a payout" and "anyone who finds this URL can credit
        # or manipulate any account".
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature")

    event_type = event.get("type")

    if event_type == "payout.failed":
        await handle_stripe_payout_failed_event(db, event)
    else:
        await handle_stripe_webhook_event(db, event)

    await db.commit()
    return {"received": True}


@router.post("/mpesa/stk-callback", status_code=status.HTTP_200_OK)
async def mpesa_stk_callback(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.json()

    await handle_mpesa_stk_callback(db, payload)
    await db.commit()

    # Daraja expects this exact shape acknowledging receipt, regardless
    # of what we did with it — it just wants confirmation the callback
    # arrived, not a description of our processing.
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/mpesa/b2c-result", status_code=status.HTTP_200_OK)
async def mpesa_b2c_result(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.json()

    await handle_mpesa_b2c_result(db, payload)
    await db.commit()

    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/mpesa/b2c-timeout", status_code=status.HTTP_200_OK)
async def mpesa_b2c_timeout(request: Request):
    """
    Daraja calls this if the B2C ResultURL callback itself times out
    (rather than the underlying payment failing) — a separate failure
    mode from a normal failed result. Logged, not yet acted on: the
    payout stays 'pending' rather than being auto-reversed here, since a
    QueueTimeOut doesn't necessarily mean the payment didn't go through
    — reconciling a genuinely stuck pending payout needs a manual/admin
    look, which is out of scope for this pass.
    """
    payload = await request.json()
    logger.warning("M-Pesa B2C queue timeout: %s", payload)
    return {"ResultCode": 0, "ResultDesc": "Accepted"}
