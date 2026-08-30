import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_verified_user
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.user import User
from app.schemas.transaction import TransactionResponse, TransferCreate
from app.services.audit_service import log_action
from app.services.transfer_service import InsufficientFundsError, execute_transfer
from app.tasks.transfer_tasks import send_transfer_confirmation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.post("", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_transfer(
    request: Request,
    payload: TransferCreate,
    current_user: User = Depends(get_current_verified_user),
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
        await log_action(
            db,
            request=request,
            action="transfer_failed_insufficient_funds",
            user_id=current_user.id,
            detail=f"to={payload.to_email} amount={payload.amount}",
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient funds")

    await log_action(
        db,
        request=request,
        action="transfer_completed",
        user_id=current_user.id,
        detail=f"to={payload.to_email} amount={payload.amount} transaction_id={transaction.id}",
    )
    await db.commit()

    # Fire-and-forget: queues to Celery, doesn't block the HTTP response
    # on notification delivery. If the broker is unreachable, the transfer
    # itself has already succeeded and been committed — we log and move on
    # rather than fail the whole request over a notification.
    try:
        send_transfer_confirmation.delay(
            transaction_id=str(transaction.id),
            from_email=current_user.email,
            to_email=payload.to_email,
            amount=str(payload.amount),
        )
    except Exception:
        logger.exception("Failed to queue transfer confirmation task for transaction %s", transaction.id)

    return transaction
