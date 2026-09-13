import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.models import Account
from app.modules.accounts.repository import AccountRepository
from app.modules.transactions.models import (
    Transaction,
    TransactionStatus,
    TransactionType,
)


class TransferRepository:
    """
    Transfers doesn't own a table of its own — a transfer is just two
    Account balance updates plus a Transaction row, both belonging to
    their own modules. This repository doesn't duplicate that data
    access; it composes AccountRepository and owns the one piece of
    logic that's genuinely specific to transfers: locking two accounts
    together in a deadlock-safe order and writing the resulting ledger
    entry as a single unit.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._account_repo = AccountRepository(db)

    async def get_accounts_for_users(
        self, from_user_id: uuid.UUID, to_user_id: uuid.UUID
    ) -> tuple[Account | None, Account | None]:
        from_account = await self._account_repo.get_by_user_id(from_user_id)
        to_account = await self._account_repo.get_by_user_id(to_user_id)
        return from_account, to_account

    async def lock_accounts_in_order(self, account_ids: list[uuid.UUID]) -> dict[uuid.UUID, Account]:
        """
        Locks each account with SELECT ... FOR UPDATE, always in
        ascending id order regardless of transfer direction, so two
        simultaneous transfers between the same two accounts (in either
        direction) can never deadlock each other.
        """
        locked_accounts: dict[uuid.UUID, Account] = {}
        for account_id in sorted(account_ids):
            locked_accounts[account_id] = await self._account_repo.get_by_id_locked(account_id)
        return locked_accounts

    async def record_transfer(
        self,
        *,
        from_account: Account,
        to_account: Account,
        amount: Decimal,
        reference_note: str | None,
    ) -> Transaction:
        """
        Applies the balance change to both (already-locked) accounts and
        writes the single immutable Transaction row that is the actual
        source of truth for the transfer. Flushes, doesn't commit — the
        caller's DB transaction (which may also include an audit log
        entry) commits as one atomic unit.
        """
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
        self.db.add(transaction)
        await self.db.flush()
        return transaction
