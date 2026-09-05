import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_verified_user
from app.core.limiter import limiter
from app.db.session import get_db
from app.modules.audit.service import log_action
from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import notify
from app.modules.transactions.schemas import TransactionResponse
from app.modules.transfers.schemas import TransferCreate
from app.modules.transfers.service import (
    AccountNotFoundError,
    InsufficientFundsError,
    RecipientNotFoundError,
    SelfTransferError,
    execute_transfer,
)
from app.modules.transfers.tasks import send_transfer_confirmation
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

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
    except SelfTransferError:
        # BUG FIX: previously execute_transfer raised HTTPException directly
        # for this case, which meant it was never audit-logged (only
        # InsufficientFundsError was caught here). Now every failure mode
        # goes through the same log-then-respond path.
        await log_action(
            db,
            request=request,
            action="transfer_failed_self_transfer",
            user_id=current_user.id,
            detail=f"to={payload.to_email}",
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot transfer to yourself")
    except RecipientNotFoundError:
        await log_action(
            db,
            request=request,
            action="transfer_failed_recipient_not_found",
            user_id=current_user.id,
            detail=f"to={payload.to_email}",
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipient not found")
    except AccountNotFoundError:
        await log_action(
            db,
            request=request,
            action="transfer_failed_account_not_found",
            user_id=current_user.id,
            detail=f"to={payload.to_email}",
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    await log_action(
        db,
        request=request,
        action="transfer_completed",
        user_id=current_user.id,
        detail=f"to={payload.to_email} amount={payload.amount} transaction_id={transaction.id}",
    )

    # Recipient is guaranteed to exist here — execute_transfer already
    # validated this above (RecipientNotFoundError would have fired
    # otherwise). Re-fetching rather than threading it back from
    # execute_transfer keeps that function's return type simple.
    recipient = await UserRepository(db).get_by_email(payload.to_email)

    await notify(
        db,
        user_id=current_user.id,
        user_email=current_user.email,
        type=NotificationType.transfer_sent,
        title="Money sent",
        body=f"You sent {payload.amount} to {payload.to_email}.",
    )
    await notify(
        db,
        user_id=recipient.id,
        user_email=recipient.email,
        type=NotificationType.transfer_received,
        title="Money received",
        body=f"You received {payload.amount} from {current_user.email}.",
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
