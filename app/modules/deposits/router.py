from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.limiter import limiter
from app.db.session import get_db
from app.modules.accounts.repository import AccountRepository
from app.modules.deposits.repository import DepositRepository
from app.modules.deposits.schemas import (
    DepositListResponse,
    MpesaDepositCreate,
    MpesaDepositResponse,
    StripeDepositCreate,
    StripeDepositResponse,
)
from app.modules.deposits.service import (
    InvalidPhoneNumber,
    MpesaRequestFailed,
    create_mpesa_deposit,
    create_stripe_deposit,
)
from app.modules.users.models import User

router = APIRouter(prefix="/deposits", tags=["deposits"])


async def _get_own_account_id(db: AsyncSession, user: User):
    account = await AccountRepository(db).get_by_user_id(user.id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account.id


@router.post("/stripe", response_model=StripeDepositResponse)
@limiter.limit("10/minute")
async def deposit_via_stripe(
    request: Request,
    payload: StripeDepositCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    account_id = await _get_own_account_id(db, current_user)

    client_secret, deposit_id = await create_stripe_deposit(
        db,
        user=current_user,
        account_id=account_id,
        amount=payload.amount,
        currency=payload.currency,
        idempotency_key=payload.idempotency_key,
    )
    await db.commit()
    return StripeDepositResponse(client_secret=client_secret, deposit_id=deposit_id)


@router.post("/mpesa", response_model=MpesaDepositResponse)
@limiter.limit("10/minute")
async def deposit_via_mpesa(
    request: Request,
    payload: MpesaDepositCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    account_id = await _get_own_account_id(db, current_user)

    try:
        deposit_id = await create_mpesa_deposit(
            db,
            user=current_user,
            account_id=account_id,
            phone_number=payload.phone_number,
            amount=payload.amount,
            idempotency_key=payload.idempotency_key,
        )
    except InvalidPhoneNumber as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except MpesaRequestFailed as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    await db.commit()
    return MpesaDepositResponse(deposit_id=deposit_id)


@router.get("", response_model=DepositListResponse)
async def list_my_deposits(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await DepositRepository(db).list_for_user(current_user.id, page=page, page_size=page_size)
    return DepositListResponse(items=items, total=total, page=page, page_size=page_size)
