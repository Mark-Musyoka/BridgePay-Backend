import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.modules.payment_methods.repository import PaymentMethodRepository
from app.modules.payment_methods.schemas import (
    LinkMpesaRequest,
    PaymentMethodResponse,
    StripeConfirmCardRequest,
    StripeSetupIntentResponse,
)
from app.modules.payment_methods.service import (
    DuplicatePaymentMethod,
    InvalidPhoneNumber,
    PaymentMethodNotFound,
    confirm_stripe_card,
    create_stripe_setup_intent,
    delete_payment_method,
    link_mpesa_number,
)
from app.modules.users.models import User

router = APIRouter(prefix="/payment-methods", tags=["payment-methods"])


@router.get("", response_model=list[PaymentMethodResponse])
async def list_payment_methods(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await PaymentMethodRepository(db).list_for_user(current_user.id)


@router.post("/stripe/setup-intent", response_model=StripeSetupIntentResponse)
async def start_stripe_card_link(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    client_secret = await create_stripe_setup_intent(db, current_user)
    await db.commit()
    return StripeSetupIntentResponse(client_secret=client_secret)


@router.post("/stripe/confirm", response_model=PaymentMethodResponse, status_code=status.HTTP_201_CREATED)
async def confirm_stripe_card_link(
    payload: StripeConfirmCardRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        method = await confirm_stripe_card(
            db, user=current_user, payment_method_id=payload.payment_method_id, set_as_default=payload.set_as_default
        )
    except PaymentMethodNotFound as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    await db.commit()
    return method


@router.post("/mpesa", response_model=PaymentMethodResponse, status_code=status.HTTP_201_CREATED)
async def link_mpesa(
    payload: LinkMpesaRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        method = await link_mpesa_number(
            db, user=current_user, phone_number=payload.phone_number, set_as_default=payload.set_as_default
        )
    except InvalidPhoneNumber as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except DuplicatePaymentMethod as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    await db.commit()
    return method


@router.delete("/{method_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_payment_method(
    method_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        method_uuid = uuid.UUID(method_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment method not found")

    try:
        await delete_payment_method(db, user=current_user, method_id=method_uuid)
    except PaymentMethodNotFound:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment method not found")

    await db.commit()
    return None
