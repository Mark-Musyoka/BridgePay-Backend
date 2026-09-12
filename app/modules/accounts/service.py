import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.models import Account
from app.modules.accounts.repository import AccountRepository


class AccountNotFound(Exception):
    pass


async def get_my_account(db: AsyncSession, *, user_id: uuid.UUID) -> Account:
    """
    Thin today — one lookup, one error case — but this is where account
    business logic (e.g. a future "account summary" combining balance
    with recent activity, or per-currency sub-accounts) would grow, so
    the router stays a pure HTTP layer rather than reaching into the
    repository directly.
    """
    account = await AccountRepository(db).get_by_user_id(user_id)
    if account is None:
        raise AccountNotFound(f"No account found for user {user_id}")
    return account
