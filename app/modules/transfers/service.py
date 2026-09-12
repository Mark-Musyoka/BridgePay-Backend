from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.transactions.models import Transaction
from app.modules.transfers.repository import TransferRepository
from app.modules.users.models import User
from app.modules.users.repository import UserRepository


class InsufficientFundsError(Exception):
    pass


class SelfTransferError(Exception):
    pass


class RecipientNotFoundError(Exception):
    pass


class AccountNotFoundError(Exception):
    pass


async def execute_transfer(
    db: AsyncSession,
    *,
    from_user: User,
    to_email: str,
    amount: Decimal,
    reference_note: str | None,
) -> Transaction:
    """
    Move `amount` from from_user's account to the account belonging to the
    user with `to_email`, atomically and safely under concurrent requests.

    Raises plain domain exceptions rather than HTTPException — this keeps
    the service layer free of transport-layer concerns, and lets the
    router (which does know about HTTP and about audit logging) decide
    how to respond to and log each failure mode consistently.

    Safety approach (implemented in TransferRepository — this function
    owns the business rules, the repository owns the row locking and
    ledger write):
    - Both account rows are locked with SELECT ... FOR UPDATE, in a
      consistent order (lower account id first), so two simultaneous
      transfers between the same two accounts can never deadlock each
      other.
    - Balance is re-checked *after* acquiring the lock, not before — a
      check-then-act without a lock is exactly the race condition this
      guards against.
    - The transaction row is the source of truth; account.balance is a
      cached mirror updated in the same DB transaction.
    """
    if from_user.email == to_email:
        raise SelfTransferError("Cannot transfer to yourself")

    to_user = await UserRepository(db).get_by_email(to_email)
    if to_user is None:
        raise RecipientNotFoundError("Recipient not found")

    transfer_repo = TransferRepository(db)
    from_account, to_account = await transfer_repo.get_accounts_for_users(from_user.id, to_user.id)
    if from_account is None or to_account is None:
        raise AccountNotFoundError("Account not found")

    locked_accounts = await transfer_repo.lock_accounts_in_order([from_account.id, to_account.id])
    from_account = locked_accounts[from_account.id]
    to_account = locked_accounts[to_account.id]

    if from_account.balance < amount:
        raise InsufficientFundsError("Insufficient funds")

    return await transfer_repo.record_transfer(
        from_account=from_account, to_account=to_account, amount=amount, reference_note=reference_note
    )
