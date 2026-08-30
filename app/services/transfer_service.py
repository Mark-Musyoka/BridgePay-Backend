from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import User
from app.repositories.account_repository import AccountRepository
from app.repositories.user_repository import UserRepository


class InsufficientFundsError(Exception):
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

    Safety approach:
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot transfer to yourself")

    account_repo = AccountRepository(db)

    to_user = await UserRepository(db).get_by_email(to_email)
    if to_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipient not found")

    from_account = await account_repo.get_by_user_id(from_user.id)
    to_account = await account_repo.get_by_user_id(to_user.id)

    if from_account is None or to_account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    # Lock both rows in a fixed order (by id) to avoid deadlocks between
    # two transfers going in opposite directions at the same time.
    account_ids_in_order = sorted([from_account.id, to_account.id])
    locked_accounts = {}
    for acc_id in account_ids_in_order:
        locked_accounts[acc_id] = await account_repo.get_by_id_locked(acc_id)

    from_account = locked_accounts[from_account.id]
    to_account = locked_accounts[to_account.id]

    if from_account.balance < amount:
        raise InsufficientFundsError("Insufficient funds")

    from_account.balance -= amount
    to_account.balance += amount

    transaction = Transaction(
        from_account_id=from_account.id,
        to_account_id=to_account.id,
        amount=amount,
        currency=from_account.currency,
        status=TransactionStatus.completed,
        type=TransactionType.transfer,
        reference_note=reference_note,
    )
    db.add(transaction)

    # Flush (not commit) — the caller commits, so this transfer and any
    # audit log entry it adds land in the same atomic DB transaction.
    await db.flush()
    return transaction
