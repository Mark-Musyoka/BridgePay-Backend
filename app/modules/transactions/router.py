from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.modules.accounts.repository import AccountRepository
from app.modules.transactions.repository import TransactionRepository
from app.modules.transactions.schemas import TransactionListResponse
from app.modules.users.models import User

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=TransactionListResponse)
async def list_my_transactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    account = await AccountRepository(db).get_by_user_id(current_user.id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    items, total = await TransactionRepository(db).list_for_account(account.id, page=page, page_size=page_size)
    return TransactionListResponse(items=items, total=total, page=page, page_size=page_size)
