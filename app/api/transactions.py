from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.account import Account
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.transaction import TransactionListResponse

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=TransactionListResponse)
async def list_my_transactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    account_result = await db.execute(select(Account.id).where(Account.user_id == current_user.id))
    account_id = account_result.scalar_one()

    base_filter = or_(
        Transaction.from_account_id == account_id,
        Transaction.to_account_id == account_id,
    )

    total_result = await db.execute(select(func.count()).select_from(Transaction).where(base_filter))
    total = total_result.scalar_one()

    items_result = await db.execute(
        select(Transaction)
        .where(base_filter)
        .order_by(Transaction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = items_result.scalars().all()

    return TransactionListResponse(items=items, total=total, page=page, page_size=page_size)
