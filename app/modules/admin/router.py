from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_admin_user
from app.db.session import get_db
from app.modules.accounts.repository import AccountRepository
from app.modules.audit.repository import AuditLogRepository
from app.modules.audit.schemas import AuditLogListResponse
from app.modules.transactions.repository import TransactionRepository
from app.modules.transactions.schemas import TransactionListResponse
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/transactions", response_model=TransactionListResponse)
async def list_all_transactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_email: str | None = Query(default=None, description="Filter to transactions involving this user's account"),
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    account_id = None
    if user_email:
        target_user = await UserRepository(db).get_by_email(user_email)
        if target_user is None:
            return TransactionListResponse(items=[], total=0, page=page, page_size=page_size)
        account = await AccountRepository(db).get_by_user_id(target_user.id)
        if account is None:
            return TransactionListResponse(items=[], total=0, page=page, page_size=page_size)
        account_id = account.id

    items, total = await TransactionRepository(db).list_all(page=page, page_size=page_size, account_id=account_id)
    return TransactionListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    action: str | None = Query(default=None, description="Filter by action type, e.g. 'login_failed'"),
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await AuditLogRepository(db).list_all(page=page, page_size=page_size, action=action)
    return AuditLogListResponse(items=items, total=total, page=page, page_size=page_size)
