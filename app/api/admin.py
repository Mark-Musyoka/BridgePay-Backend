from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin_user
from app.db.session import get_db
from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.admin import AuditLogResponse, AuditLogListResponse
from app.schemas.transaction import TransactionListResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/transactions", response_model=TransactionListResponse)
async def list_all_transactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_email: str | None = Query(default=None, description="Filter to transactions involving this user's account"),
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Transaction)
    count_query = select(func.count()).select_from(Transaction)

    if user_email:
        account_result = await db.execute(
            select(Account.id).join(User, User.id == Account.user_id).where(User.email == user_email)
        )
        account_id = account_result.scalar_one_or_none()
        if account_id is None:
            return TransactionListResponse(items=[], total=0, page=page, page_size=page_size)

        account_filter = or_(
            Transaction.from_account_id == account_id,
            Transaction.to_account_id == account_id,
        )
        query = query.where(account_filter)
        count_query = count_query.where(account_filter)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    items_result = await db.execute(
        query.order_by(Transaction.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = items_result.scalars().all()

    return TransactionListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    action: str | None = Query(default=None, description="Filter by action type, e.g. 'login_failed'"),
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(AuditLog)
    count_query = select(func.count()).select_from(AuditLog)

    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    items_result = await db.execute(
        query.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = items_result.scalars().all()

    return AuditLogListResponse(items=items, total=total, page=page, page_size=page_size)
