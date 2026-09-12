import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.repository import AccountRepository
from app.modules.audit.models import AuditLog
from app.modules.audit.repository import AuditLogRepository
from app.modules.transactions.models import Transaction
from app.modules.transactions.repository import TransactionRepository
from app.modules.users.repository import UserRepository


class AdminRepository:
    """
    Admin owns no table of its own — every query here composes the
    repositories of the modules that actually own the data (accounts,
    users, transactions, audit). This class exists so the router doesn't
    import four other modules' repositories directly; it's the one place
    admin-specific data access (like "which account belongs to this
    email") lives.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve_account_id_for_email(self, email: str) -> uuid.UUID | None:
        """Returns None if there's no user with this email, or the user
        has no account — both cases mean "nothing to filter by", which
        the caller turns into an empty result set rather than an error,
        since a typo'd admin filter shouldn't look like a server error."""
        user = await UserRepository(self.db).get_by_email(email)
        if user is None:
            return None
        account = await AccountRepository(self.db).get_by_user_id(user.id)
        if account is None:
            return None
        return account.id

    async def list_transactions(
        self, *, page: int, page_size: int, account_id: uuid.UUID | None = None
    ) -> tuple[list[Transaction], int]:
        return await TransactionRepository(self.db).list_all(page=page, page_size=page_size, account_id=account_id)

    async def list_audit_logs(
        self, *, page: int, page_size: int, action: str | None = None
    ) -> tuple[list[AuditLog], int]:
        return await AuditLogRepository(self.db).list_all(page=page, page_size=page_size, action=action)
