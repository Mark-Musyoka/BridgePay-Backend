from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.transaction import TransactionResponse, TransferCreate
from app.services.transfer_service import InsufficientFundsError, execute_transfer

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.post("", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transfer(
    payload: TransferCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        transaction = await execute_transfer(
            db,
            from_user=current_user,
            to_email=payload.to_email,
            amount=payload.amount,
            reference_note=payload.reference_note,
        )
    except InsufficientFundsError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient funds")

    return transaction
