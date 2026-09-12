from app.modules.admin.repository import AdminRepository
from app.modules.audit.models import AuditLog
from app.modules.transactions.models import Transaction
from sqlalchemy.ext.asyncio import AsyncSession


async def list_transactions_for_admin(
    db: AsyncSession, *, page: int, page_size: int, user_email: str | None = None
) -> tuple[list[Transaction], int]:
    """
    If user_email is given but doesn't resolve to an account, returns an
    empty page rather than a 404 — an admin searching by email typo'd
    or for a user who never completed signup should see "no results",
    the same as any other filter that happens to match nothing.
    """
    repo = AdminRepository(db)
    account_id = None
    if user_email is not None:
        account_id = await repo.resolve_account_id_for_email(user_email)
        if account_id is None:
            return [], 0
    return await repo.list_transactions(page=page, page_size=page_size, account_id=account_id)


async def list_audit_logs_for_admin(
    db: AsyncSession, *, page: int, page_size: int, action: str | None = None
) -> tuple[list[AuditLog], int]:
    return await AdminRepository(db).list_audit_logs(page=page, page_size=page_size, action=action)
