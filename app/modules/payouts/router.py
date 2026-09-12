from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_verified_user
from app.core.exchange_rate_client import ExchangeRateUnavailable
from app.core.limiter import limiter
from app.db.session import get_db
from app.modules.accounts.repository import AccountRepository
from app.modules.payouts.repository import PayoutRepository
from app.modules.payouts.schemas import (
    AirtelPayoutCreate,
    MpesaPayoutCreate,
    PayoutListResponse,
    PayoutResponse,
    StripeCardPayoutCreate,
)
from app.modules.payouts.service import (
    AirtelRequestFailed,
    InsufficientFundsError,
    InvalidPhoneNumber,
    MpesaRequestFailed,
    StripePayoutFailed,
    create_airtel_payout,
    create_mpesa_payout,
    create_stripe_card_payout,
)
from app.modules.users.models import User

router = APIRouter(prefix="/payouts", tags=["payouts"])


async def _get_own_account_id(db: AsyncSession, user: User):
    account = await AccountRepository(db).get_by_user_id(user.id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account.id


@router.post("/mpesa", response_model=PayoutResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def payout_via_mpesa(
    request: Request,
    payload: MpesaPayoutCreate,
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db),
):
    account_id = await _get_own_account_id(db, current_user)

    try:
        payout = await create_mpesa_payout(
            db,
            user=current_user,
            account_id=account_id,
            phone_number=payload.phone_number,
            recipient_email=payload.recipient_email,
            amount=payload.amount,
            idempotency_key=payload.idempotency_key,
        )
    except InsufficientFundsError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient funds")
    except ExchangeRateUnavailable as e:
        # Fails inside _deduct_balance_and_record, before any external
        # API call — nothing to reverse, a plain rollback is enough.
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except InvalidPhoneNumber as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except MpesaRequestFailed as e:
        # The balance was already reversed inside create_mpesa_payout —
        # commit that reversal, don't roll it back too.
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    await db.commit()
    return payout


@router.post("/stripe-card", response_model=PayoutResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def payout_via_stripe_card(
    request: Request,
    payload: StripeCardPayoutCreate,
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db),
):
    account_id = await _get_own_account_id(db, current_user)

    try:
        payout = await create_stripe_card_payout(
            db,
            user=current_user,
            account_id=account_id,
            card_token=payload.card_token,
            recipient_email=payload.recipient_email,
            amount=payload.amount,
            currency=payload.currency,
            idempotency_key=payload.idempotency_key,
        )
    except InsufficientFundsError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient funds")
    except ExchangeRateUnavailable as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except StripePayoutFailed as e:
        await db.commit()  # reversal already happened, commit it
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    await db.commit()
    return payout


@router.post("/airtel", response_model=PayoutResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def payout_via_airtel(
    request: Request,
    payload: AirtelPayoutCreate,
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db),
):
    account_id = await _get_own_account_id(db, current_user)

    try:
        payout = await create_airtel_payout(
            db,
            user=current_user,
            account_id=account_id,
            phone_number=payload.phone_number,
            recipient_email=payload.recipient_email,
            amount=payload.amount,
            idempotency_key=payload.idempotency_key,
        )
    except InsufficientFundsError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient funds")
    except ExchangeRateUnavailable as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except InvalidPhoneNumber as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except AirtelRequestFailed as e:
        await db.commit()  # balance was already reversed inside create_airtel_payout
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    await db.commit()
    return payout


@router.get("", response_model=PayoutListResponse)
async def list_my_payouts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await PayoutRepository(db).list_for_user(current_user.id, page=page, page_size=page_size)
    return PayoutListResponse(items=items, total=total, page=page, page_size=page_size)
