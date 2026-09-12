import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import get_my_account
from app.modules.transactions.models import Transaction
from app.modules.transactions.repository import TransactionRepository

# Re-exported so callers (the router) only need to import from this
# module, not reach into accounts.service directly for an error that's
# raised as a side effect of building someone's transaction history.
from app.modules.accounts.service import AccountNotFound  # noqa: F401


async def list_my_transactions(
    db: AsyncSession, *, user_id: uuid.UUID, page: int, page_size: int
) -> tuple[list[Transaction], int]:
    """
    Resolves the caller's account, then paginates their transaction
    history. Raises AccountNotFound (propagated from accounts.service)
    if the user somehow has no account — every user is meant to get one
    at registration, so this would indicate a data problem, not a normal
    404.
    """
    account = await get_my_account(db, user_id=user_id)
    return await TransactionRepository(db).list_for_account(account.id, page=page, page_size=page_size)
