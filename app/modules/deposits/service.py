import uuid
from decimal import ROUND_HALF_UP, Decimal

import httpx
from sqlalchemy import select

from app.core.airtel_client import get_access_token as get_airtel_access_token
from app.core.airtel_client import get_base_url as get_airtel_base_url
from app.core.airtel_client import normalize_kenyan_phone as normalize_airtel_phone
from app.core.airtel_client import standard_headers as airtel_standard_headers
from app.core.config import settings
from app.core.exchange_rate_client import ExchangeRateUnavailable, convert
from app.core.mpesa_client import (
    current_timestamp,
    generate_stk_password,
    get_access_token,
    get_base_url,
    normalize_kenyan_phone,
)
from app.core.stripe_client import stripe
from app.modules.accounts.repository import AccountRepository
from app.modules.deposits.models import Deposit, DepositProvider
from app.modules.deposits.repository import DepositRepository
from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import notify
from app.modules.transactions.models import (
    Transaction,
    TransactionStatus,
    TransactionType,
)
from app.modules.users.models import User


class InvalidPhoneNumber(Exception):
    pass


class MpesaRequestFailed(Exception):
    pass


class AirtelRequestFailed(Exception):
    pass


async def _get_user(db, user_id: uuid.UUID) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one()


async def _credit_account_and_record(db, *, deposit: Deposit) -> None:
    """
    Shared completion path for both providers: lock the account, convert
    the deposit into the account's own currency if they differ, credit
    it, write the immutable Transaction row (in the account's currency —
    it's a ledger of what actually moved through the account, not of
    what the depositor typed in), mark the deposit completed, and notify
    — all inside the caller's DB transaction (flush, not commit; the
    router/webhook handler commits).

    Only ever called after a webhook confirms success — never
    optimistically when the deposit is first created, since the money
    isn't actually there yet at that point for either provider.

    Previously this credited deposit.amount directly regardless of
    currency — fine for M-Pesa (always KES, matching the account
    default) but wrong the moment a Stripe deposit came in in a
    non-account currency: it credited the raw foreign-currency number as
    if it were KES.
    """
    account_repo = AccountRepository(db)
    account = await account_repo.get_by_id_locked(deposit.account_id)

    try:
        converted_amount, exchange_rate = await convert(deposit.amount, deposit.currency, account.currency)
    except ExchangeRateUnavailable as e:
        await DepositRepository(db).mark_failed(deposit, reason=f"Currency conversion failed: {e}")
        user = await _get_user(db, deposit.user_id)
        await notify(
            db,
            user_id=deposit.user_id,
            user_email=user.email,
            type=NotificationType.deposit_failed,
            title="Deposit failed",
            body=(
                f"Your deposit of {deposit.amount} {deposit.currency} could not be completed: "
                "a currency conversion rate was unavailable. No funds were charged."
            ),
        )
        return

    account.balance += converted_amount

    if deposit.currency.upper() != account.currency.upper():
        await DepositRepository(db).set_conversion(
            deposit, exchange_rate=exchange_rate, converted_amount=converted_amount
        )

    transaction = Transaction(
        from_account_id=None,
        to_account_id=account.id,
        amount=converted_amount,
        currency=account.currency,
        status=TransactionStatus.completed,
        type=TransactionType.deposit,
        reference_note=f"{deposit.provider.value} deposit",
    )
    db.add(transaction)

    await DepositRepository(db).mark_completed(deposit)

    user = await _get_user(db, deposit.user_id)
    await notify(
        db,
        user_id=deposit.user_id,
        user_email=user.email,
        type=NotificationType.deposit_completed,
        title="Deposit successful",
        body=f"Your deposit of {deposit.amount} {deposit.currency} has been credited to your wallet.",
    )


# --- Stripe -------------------------------------------------------------

async def create_stripe_deposit(
    db, *, user: User, account_id: uuid.UUID, amount: Decimal, currency: str, idempotency_key: str | None
) -> tuple[str, uuid.UUID]:
    deposit_repo = DepositRepository(db)

    if idempotency_key:
        existing = await deposit_repo.get_by_idempotency_key_for_user(user.id, idempotency_key)
        if existing is not None:
            # Same request retried — return the SAME PaymentIntent's
            # client_secret rather than creating a second charge.
            pi = stripe.PaymentIntent.retrieve(existing.external_reference)
            return pi.client_secret, existing.id

    from app.modules.payment_methods.service import ensure_stripe_customer

    customer_id = await ensure_stripe_customer(db, user)

    amount_in_smallest_unit = int(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)

    payment_intent = stripe.PaymentIntent.create(
        amount=amount_in_smallest_unit,
        currency=currency.lower(),
        customer=customer_id,
        metadata={"user_id": str(user.id), "account_id": str(account_id)},
    )

    deposit = await deposit_repo.create(
        user_id=user.id,
        account_id=account_id,
        provider=DepositProvider.stripe,
        amount=amount,
        currency=currency.upper(),
        external_reference=payment_intent.id,
        idempotency_key=idempotency_key,
    )

    return payment_intent.client_secret, deposit.id


async def handle_stripe_webhook_event(db, event: dict) -> None:
    event_type = event.get("type")
    pi_data = event.get("data", {}).get("object", {})
    pi_id = pi_data.get("id")
    if not pi_id:
        return

    deposit = await DepositRepository(db).get_by_external_reference(pi_id)
    if deposit is None:
        # Not a deposit we initiated (or a PaymentIntent used for
        # something else entirely) — nothing for us to do.
        return

    if deposit.status != "pending":
        # Already processed — webhooks are delivered at-least-once by
        # design, this makes reprocessing a safe no-op.
        return

    if event_type == "payment_intent.succeeded":
        await _credit_account_and_record(db, deposit=deposit)
    elif event_type == "payment_intent.payment_failed":
        reason = pi_data.get("last_payment_error", {}).get("message", "Payment failed")
        await DepositRepository(db).mark_failed(deposit, reason=reason)

        user = await _get_user(db, deposit.user_id)
        await notify(
            db,
            user_id=deposit.user_id,
            user_email=user.email,
            type=NotificationType.deposit_failed,
            title="Deposit failed",
            body=f"Your deposit of {deposit.amount} {deposit.currency} could not be completed: {reason}",
        )


# --- M-Pesa STK Push ------------------------------------------------------

async def create_mpesa_deposit(
    db, *, user: User, account_id: uuid.UUID, phone_number: str, amount: Decimal, idempotency_key: str | None
) -> uuid.UUID:
    deposit_repo = DepositRepository(db)

    if idempotency_key:
        existing = await deposit_repo.get_by_idempotency_key_for_user(user.id, idempotency_key)
        if existing is not None:
            return existing.id

    try:
        normalized_phone = normalize_kenyan_phone(phone_number)
    except ValueError as e:
        raise InvalidPhoneNumber(str(e))

    access_token = await get_access_token()
    timestamp = current_timestamp()
    password = generate_stk_password(timestamp)

    payload = {
        "BusinessShortCode": settings.MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount),  # Daraja requires a whole-number amount
        "PartyA": normalized_phone,
        "PartyB": settings.MPESA_SHORTCODE,
        "PhoneNumber": normalized_phone,
        "CallBackURL": f"{settings.MPESA_CALLBACK_BASE_URL}/api/v1/webhooks/mpesa/stk-callback",
        "AccountReference": "BridgePay",
        "TransactionDesc": "Wallet deposit",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{get_base_url()}/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )

    if response.status_code != 200:
        raise MpesaRequestFailed(f"STK push request failed: {response.text}")

    data = response.json()
    checkout_request_id = data.get("CheckoutRequestID")
    if not checkout_request_id:
        raise MpesaRequestFailed(f"STK push did not return a CheckoutRequestID: {data}")

    deposit = await deposit_repo.create(
        user_id=user.id,
        account_id=account_id,
        provider=DepositProvider.mpesa,
        amount=amount,
        currency="KES",
        external_reference=checkout_request_id,
        idempotency_key=idempotency_key,
    )

    return deposit.id


async def handle_mpesa_stk_callback(db, payload: dict) -> None:
    """
    NOTE on security: unlike Stripe, Daraja does not sign its webhook
    callbacks at all — there's no equivalent of a webhook secret to
    verify. The standard mitigations (documented, not implemented here
    since they require infra-level config this codebase doesn't control)
    are: only accept requests from Safaricom's published IP ranges at
    the load balancer/firewall level, and treat the CallbackURL itself
    as a shared secret by making it hard to guess. Processing here is
    idempotent (checks deposit.status before crediting) as a second line
    of defense regardless.
    """
    callback = payload.get("Body", {}).get("stkCallback", {})
    checkout_request_id = callback.get("CheckoutRequestID")
    result_code = callback.get("ResultCode")
    result_desc = callback.get("ResultDesc", "Unknown error")

    if not checkout_request_id:
        return

    deposit = await DepositRepository(db).get_by_external_reference(checkout_request_id)
    if deposit is None or deposit.status != "pending":
        return

    if result_code == 0:
        await _credit_account_and_record(db, deposit=deposit)
    else:
        await DepositRepository(db).mark_failed(deposit, reason=result_desc)

        user = await _get_user(db, deposit.user_id)
        await notify(
            db,
            user_id=deposit.user_id,
            user_email=user.email,
            type=NotificationType.deposit_failed,
            title="Deposit failed",
            body=f"Your M-Pesa deposit of {deposit.amount} KES could not be completed: {result_desc}",
        )


# --- Airtel Money Collections (USSD push) ---------------------------------

async def create_airtel_deposit(
    db, *, user: User, account_id: uuid.UUID, phone_number: str, amount: Decimal, idempotency_key: str | None
) -> uuid.UUID:
    deposit_repo = DepositRepository(db)

    if idempotency_key:
        existing = await deposit_repo.get_by_idempotency_key_for_user(user.id, idempotency_key)
        if existing is not None:
            return existing.id

    try:
        normalized_phone = normalize_airtel_phone(phone_number)
    except ValueError as e:
        raise InvalidPhoneNumber(str(e))

    access_token = await get_airtel_access_token()
    # A fresh transaction id per attempt — this is Airtel's own
    # "transaction.id" field, distinct from the reference we use for
    # our own idempotency handling above. Unlike M-Pesa's Daraja, Airtel
    # doesn't take a per-request callback URL — it's registered once for
    # the whole application in the developer portal (AIRTEL_CALLBACK_BASE_URL
    # documents what that should point at: this app's own
    # /api/v1/webhooks/airtel/collection-callback).
    transaction_id = str(uuid.uuid4())

    payload = {
        "reference": "BridgePay deposit",
        "subscriber": {"country": "KE", "currency": "KES", "msisdn": normalized_phone},
        "transaction": {"amount": int(amount), "country": "KE", "currency": "KES", "id": transaction_id},
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{get_airtel_base_url()}/merchant/v1/payments/",
            json=payload,
            headers=airtel_standard_headers(access_token),
            timeout=30.0,
        )

    if response.status_code not in (200, 201):
        raise AirtelRequestFailed(f"Collections request failed: {response.text}")

    data = response.json()
    if not data.get("status", {}).get("success", False):
        raise AirtelRequestFailed(f"Collections request was not accepted: {data}")

    deposit = await deposit_repo.create(
        user_id=user.id,
        account_id=account_id,
        provider=DepositProvider.airtel,
        amount=amount,
        currency="KES",
        external_reference=transaction_id,
        idempotency_key=idempotency_key,
    )

    return deposit.id


async def handle_airtel_collection_callback(db, payload: dict) -> None:
    """
    Airtel's Collections callback shape: {"transaction": {"id": ...,
    "airtel_money_id": ..., "status_code": "TS"|"TF"}}. Signature
    verification happens in the router (needs the raw body, which the
    service layer never sees) before this is called — see
    webhooks/service.py's dispatch_airtel_collection_callback.
    """
    transaction = payload.get("transaction", {})
    transaction_id = transaction.get("id")
    status_code = transaction.get("status_code")

    if not transaction_id:
        return

    deposit = await DepositRepository(db).get_by_external_reference(transaction_id)
    if deposit is None or deposit.status != "pending":
        return

    if status_code == "TS":  # Transaction Successful
        await _credit_account_and_record(db, deposit=deposit)
    else:
        reason = f"Airtel Money transaction status: {status_code or 'unknown'}"
        await DepositRepository(db).mark_failed(deposit, reason=reason)

        user = await _get_user(db, deposit.user_id)
        await notify(
            db,
            user_id=deposit.user_id,
            user_email=user.email,
            type=NotificationType.deposit_failed,
            title="Deposit failed",
            body=f"Your Airtel Money deposit of {deposit.amount} KES could not be completed: {reason}",
        )
