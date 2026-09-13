import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.webhooks.schemas import (
    AirtelAckResponse,
    DarajaAckResponse,
    WebhookAckResponse,
)
from app.modules.webhooks.service import (
    InvalidWebhookSignature,
    dispatch_airtel_collection_callback,
    dispatch_airtel_disbursement_callback,
    dispatch_mpesa_b2c_result,
    dispatch_mpesa_stk_callback,
    verify_and_dispatch_stripe_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe", status_code=status.HTTP_200_OK, response_model=WebhookAckResponse)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    signature = request.headers.get("stripe-signature")

    try:
        await verify_and_dispatch_stripe_event(db, payload=payload, signature=signature)
    except InvalidWebhookSignature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature")

    await db.commit()
    return WebhookAckResponse()


@router.post("/mpesa/stk-callback", status_code=status.HTTP_200_OK, response_model=DarajaAckResponse)
async def mpesa_stk_callback(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.json()

    await dispatch_mpesa_stk_callback(db, payload)
    await db.commit()

    return DarajaAckResponse()


@router.post("/mpesa/b2c-result", status_code=status.HTTP_200_OK, response_model=DarajaAckResponse)
async def mpesa_b2c_result(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.json()

    await dispatch_mpesa_b2c_result(db, payload)
    await db.commit()

    return DarajaAckResponse()


@router.post("/mpesa/b2c-timeout", status_code=status.HTTP_200_OK, response_model=DarajaAckResponse)
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
    return DarajaAckResponse()


@router.post("/airtel/collection-callback", status_code=status.HTTP_200_OK, response_model=AirtelAckResponse)
async def airtel_collection_callback(request: Request, db: AsyncSession = Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("x-signature")

    try:
        await dispatch_airtel_collection_callback(db, raw_body=raw_body, signature=signature)
    except InvalidWebhookSignature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature")

    await db.commit()
    return AirtelAckResponse()


@router.post("/airtel/disbursement-callback", status_code=status.HTTP_200_OK, response_model=AirtelAckResponse)
async def airtel_disbursement_callback(request: Request, db: AsyncSession = Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("x-signature")

    try:
        await dispatch_airtel_disbursement_callback(db, raw_body=raw_body, signature=signature)
    except InvalidWebhookSignature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature")

    await db.commit()
    return AirtelAckResponse()
