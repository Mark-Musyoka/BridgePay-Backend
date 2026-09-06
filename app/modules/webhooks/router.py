import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.stripe_client import stripe
from app.db.session import get_db
from app.modules.deposits.service import handle_mpesa_stk_callback, handle_stripe_webhook_event

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
        # one thing standing between "only Stripe can trigger a deposit"
        # and "anyone who finds this URL can credit any account".
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature")

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
