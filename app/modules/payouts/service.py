import uuid
from decimal import ROUND_HALF_UP, Decimal

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.exchange_rate_client import ExchangeRateUnavailable, convert
from app.core.mpesa_client import (
    current_timestamp,
    generate_security_credential,
    get_access_token,
    get_base_url,
    normalize_kenyan_phone,
)
from app.core.stripe_client import stripe
from app.modules.accounts.repository import AccountRepository
from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import notify
from app.modules.payouts.models import Payout, PayoutProvider
from app.modules.payouts.repository import PayoutRepository
from app.modules.transactions.models import Transaction, TransactionStatus, TransactionType
from app.modules.users.models import User


class InsufficientFundsError(Exception):
    pass


class InvalidPhoneNumber(Exception):
    pass


class MpesaRequestFailed(Exception):
    pass


class StripePayoutFailed(Exception):
    pass


async def _get_user(db, user_id: uuid.UUID) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one()


async def _deduct_balance_and_record(
    db, *, account_id: uuid.UUID, amount: Decimal, currency: str
) -> tuple[Decimal, Decimal, str]:
    """
    The core safety-critical step, shared by both providers: lock the
    account, convert amount/currency into the account's own currency if
    they differ, verify sufficient funds, deduct — done UP FRONT, before
    any external API call, and BEFORE the Payout row's external_reference
    is even known.

    Why deduct first rather than after the payout succeeds: the external
    call can take real time (a network round-trip to Safaricom/Stripe),
    during which a second concurrent payout request must not be allowed
    to see the pre-deduction balance and also succeed — that's the same
    double-spend race the transfer locking (see transfers/service.py)
    exists to prevent, applied here to money leaving the platform rather
    than moving between two accounts. If the external call subsequently
    fails, _reverse_deduction below undoes exactly this.

    Previously this deducted `amount` directly regardless of currency —
    fine for M-Pesa (always KES, matching the account default) but wrong
    the moment a Stripe payout was requested in a non-account currency:
    it deducted the raw foreign-currency number as if it were KES.

    Returns (converted_amount, exchange_rate, account_currency) so the
    caller can decide whether a conversion actually happened (compare
    `currency` to account_currency) and, if so, persist it on the
    Payout row once that row exists.
    """
    account_repo = AccountRepository(db)
    account = await account_repo.get_by_id_locked(account_id)

    converted_amount, exchange_rate = await convert(amount, currency, account.currency)

    if account.balance < converted_amount:
        raise InsufficientFundsError("Insufficient funds")

    account.balance -= converted_amount

    transaction = Transaction(
        from_account_id=account.id,
        to_account_id=None,
        amount=converted_amount,
        currency=account.currency,
        status=TransactionStatus.completed,
        type=TransactionType.withdrawal,
        reference_note="External payout",
    )
    db.add(transaction)
    await db.flush()

    return converted_amount, exchange_rate, account.currency


async def _reverse_deduction(db, *, payout: Payout, reason: str) -> None:
    """
    Undoes _deduct_balance_and_record above. Called whenever a payout
    fails AFTER the balance was already committed to leaving — whether
    that failure is discovered synchronously (the initial API call
    itself errors) or asynchronously (a webhook/result callback reports
    failure after initially being accepted). Credits the account back,
    writes a second, separate Transaction (the ledger is immutable — a
    correction is a new opposite entry, never an edit to the original
    deduction), marks the payout reversed, and notifies the user.

    Credits back payout.converted_amount (the account-currency amount
    that was actually deducted) when a conversion happened, falling back
    to payout.amount when it didn't — never payout.amount unconditionally,
    which would credit back the wrong figure whenever the payout's
    currency differs from the account's.
    """
    account_repo = AccountRepository(db)
    account = await account_repo.get_by_id_locked(payout.account_id)

    amount_to_credit = payout.converted_amount if payout.converted_amount is not None else payout.amount
    account.balance += amount_to_credit

    reversal_transaction = Transaction(
        from_account_id=None,
        to_account_id=account.id,
        amount=amount_to_credit,
        currency=account.currency,
        status=TransactionStatus.completed,
        type=TransactionType.deposit,
        reference_note=f"Reversal of failed payout {payout.id}",
    )
    db.add(reversal_transaction)

    await PayoutRepository(db).mark_reversed(payout, reason=reason)

    user = await _get_user(db, payout.user_id)
    await notify(
        db,
        user_id=payout.user_id,
        user_email=user.email,
        type=NotificationType.payout_reversed,
        title="Payout failed — funds returned",
        body=(
            f"Your payout of {payout.amount} {payout.currency} could not be completed "
            f"({reason}) and has been returned to your wallet."
        ),
    )


# --- M-Pesa B2C -----------------------------------------------------------

async def create_mpesa_payout(
    db,
    *,
    user: User,
    account_id: uuid.UUID,
    phone_number: str,
    recipient_email: str,
    amount: Decimal,
    idempotency_key: str | None,
) -> Payout:
    payout_repo = PayoutRepository(db)

    if idempotency_key:
        existing = await payout_repo.get_by_idempotency_key_for_user(user.id, idempotency_key)
        if existing is not None:
            return existing

    try:
        normalized_phone = normalize_kenyan_phone(phone_number)
    except ValueError as e:
        raise InvalidPhoneNumber(str(e))

    # Deduct FIRST — see _deduct_balance_and_record's docstring for why.
    # Raises InsufficientFundsError before anything else happens if the
    # sender can't cover it, same as transfers/service.py.
    converted_amount, exchange_rate, account_currency = await _deduct_balance_and_record(
        db, account_id=account_id, amount=amount, currency="KES"
    )
    conversion_happened = "KES" != account_currency.upper()

    payout = await payout_repo.create(
        user_id=user.id,
        account_id=account_id,
        provider=PayoutProvider.mpesa,
        destination_reference=normalized_phone,
        recipient_email=recipient_email,
        amount=amount,
        currency="KES",
        idempotency_key=idempotency_key,
        exchange_rate=exchange_rate if conversion_happened else None,
        converted_amount=converted_amount if conversion_happened else None,
    )

    try:
        access_token = await get_access_token()
        security_credential = generate_security_credential()

        payload = {
            "InitiatorName": settings.MPESA_INITIATOR_NAME,
            "SecurityCredential": security_credential,
            "CommandID": "BusinessPayment",
            "Amount": int(amount),
            "PartyA": settings.MPESA_SHORTCODE,
            "PartyB": normalized_phone,
            "Remarks": "BridgePay payout",
            "QueueTimeOutURL": f"{settings.MPESA_CALLBACK_BASE_URL}/api/v1/webhooks/mpesa/b2c-timeout",
            "ResultURL": f"{settings.MPESA_CALLBACK_BASE_URL}/api/v1/webhooks/mpesa/b2c-result",
            "Occasion": "",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{get_base_url()}/mpesa/b2c/v1/paymentrequest",
                json=payload,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30.0,
            )

        if response.status_code != 200:
            raise MpesaRequestFailed(f"B2C request failed: {response.text}")

        data = response.json()
        conversation_id = data.get("ConversationID")
        if not conversation_id:
            raise MpesaRequestFailed(f"B2C request did not return a ConversationID: {data}")

        await payout_repo.set_external_reference(payout, conversation_id)

    except (MpesaRequestFailed, RuntimeError, httpx.HTTPError) as e:
        # The API call itself failed synchronously — never even got a
        # ConversationID to wait on a result for. Reverse immediately
        # rather than leaving the sender's money in limbo.
        await _reverse_deduction(db, payout=payout, reason=str(e))
        raise MpesaRequestFailed(str(e))

    return payout


async def handle_mpesa_b2c_result(db, payload: dict) -> None:
    """Same idempotency/security caveats as the STK Push callback in
    deposits/service.py — Daraja doesn't sign these either."""
    result = payload.get("Result", {})
    conversation_id = result.get("ConversationID")
    result_code = result.get("ResultCode")
    result_desc = result.get("ResultDesc", "Unknown error")

    if not conversation_id:
        return

    payout = await PayoutRepository(db).get_by_external_reference(conversation_id)
    if payout is None or payout.status != "pending":
        return

    if result_code == 0:
        await PayoutRepository(db).mark_completed(payout)
        user = await _get_user(db, payout.user_id)
        await notify(
            db,
            user_id=payout.user_id,
            user_email=user.email,
            type=NotificationType.payout_sent,
            title="Payout sent",
            body=f"Your payout of {payout.amount} {payout.currency} to {payout.destination_reference} was sent.",
        )
    else:
        await _reverse_deduction(db, payout=payout, reason=result_desc)


# --- Stripe card payout -----------------------------------------------------

async def create_stripe_card_payout(
    db,
    *,
    user: User,
    account_id: uuid.UUID,
    card_token: str,
    recipient_email: str,
    amount: Decimal,
    currency: str,
    idempotency_key: str | None,
) -> Payout:
    payout_repo = PayoutRepository(db)

    if idempotency_key:
        existing = await payout_repo.get_by_idempotency_key_for_user(user.id, idempotency_key)
        if existing is not None:
            return existing

    converted_amount, exchange_rate, account_currency = await _deduct_balance_and_record(
        db, account_id=account_id, amount=amount, currency=currency.upper()
    )
    conversion_happened = currency.upper() != account_currency.upper()

    payout = await payout_repo.create(
        user_id=user.id,
        account_id=account_id,
        provider=PayoutProvider.stripe,
        destination_reference=card_token,
        recipient_email=recipient_email,
        amount=amount,
        currency=currency.upper(),
        idempotency_key=idempotency_key,
        exchange_rate=exchange_rate if conversion_happened else None,
        converted_amount=converted_amount if conversion_happened else None,
    )

    amount_in_smallest_unit = int(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)

    try:
        # NOTE: stripe.Payout.create pays out FROM the platform's own
        # Stripe balance TO a destination — "push to card" like this
        # requires the account to have Instant Payouts / the relevant
        # capability enabled, which isn't automatic on a standard
        # account. This is the one piece of this module most likely to
        # need adjustment once tested against a real Stripe account —
        # flagged clearly rather than assumed to just work.
        payout_result = stripe.Payout.create(
            amount=amount_in_smallest_unit,
            currency=currency.lower(),
            method="instant",
            destination=card_token,
        )
        await payout_repo.set_external_reference(payout, payout_result.id)

        if payout_result.status == "failed":
            await _reverse_deduction(db, payout=payout, reason="Stripe payout failed immediately")
        else:
            # Stripe payouts can still fail later — see the
            # payout.failed webhook handling below for that case.
            await payout_repo.mark_completed(payout)
            user = await _get_user(db, payout.user_id)
            await notify(
                db,
                user_id=payout.user_id,
                user_email=user.email,
                type=NotificationType.payout_sent,
                title="Payout sent",
                body=f"Your payout of {payout.amount} {payout.currency} was sent to the linked card.",
            )

    except stripe.error.StripeError as e:
        await _reverse_deduction(db, payout=payout, reason=str(e))
        raise StripePayoutFailed(str(e))

    return payout


async def handle_stripe_payout_failed_event(db, event: dict) -> None:
    """Handles the case where a Stripe payout initially looked fine but
    fails later (e.g. the destination card was declined/closed) — Stripe
    reports this asynchronously via payout.failed."""
    payout_data = event.get("data", {}).get("object", {})
    payout_id = payout_data.get("id")
    if not payout_id:
        return

    payout = await PayoutRepository(db).get_by_external_reference(payout_id)
    if payout is None or payout.status != "completed":
        # Either not ours, or already reversed/failed — don't double-reverse.
        return

    reason = payout_data.get("failure_message", "Payout failed after being sent")
    await _reverse_deduction(db, payout=payout, reason=reason)
