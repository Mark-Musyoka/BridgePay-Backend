from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_admin_user
from app.db.session import get_db
from app.modules.admin.schemas import AuditLogListResponse, TransactionListResponse
from app.modules.admin.service import (
    list_audit_logs_for_admin,
    list_transactions_for_admin,
)
from app.modules.users.models import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/transactions", response_model=TransactionListResponse)
async def list_all_transactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_email: str | None = Query(default=None, description="Filter to transactions involving this user's account"),
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_transactions_for_admin(db, page=page, page_size=page_size, user_email=user_email)
    return TransactionListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    action: str | None = Query(default=None, description="Filter by action type, e.g. 'login_failed'"),
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await list_audit_logs_for_admin(db, page=page, page_size=page_size, action=action)
    return AuditLogListResponse(items=items, total=total, page=page, page_size=page_size)
