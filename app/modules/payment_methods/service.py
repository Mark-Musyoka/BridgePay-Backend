from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mpesa_client import normalize_kenyan_phone
from app.core.stripe_client import stripe
from app.modules.payment_methods.models import PaymentMethod, PaymentMethodProvider, PaymentMethodType
from app.modules.payment_methods.repository import PaymentMethodRepository
from app.modules.users.models import User


class PaymentMethodNotFound(Exception):
    pass


class DuplicatePaymentMethod(Exception):
    pass


class InvalidPhoneNumber(Exception):
    pass


async def ensure_stripe_customer(db: AsyncSession, user: User) -> str:
    """Stripe Customers are required for an off-session-reusable
    SetupIntent. Created lazily on first Stripe interaction — most users
    (e.g. M-Pesa-only ones) will never need one at all."""
    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer = stripe.Customer.create(email=user.email, name=user.full_name, metadata={"user_id": str(user.id)})
    user.stripe_customer_id = customer.id
    await db.flush()
    return customer.id


async def create_stripe_setup_intent(db: AsyncSession, user: User) -> str:
    customer_id = await ensure_stripe_customer(db, user)
    setup_intent = stripe.SetupIntent.create(customer=customer_id, usage="off_session")
    return setup_intent.client_secret


async def confirm_stripe_card(
    db: AsyncSession, *, user: User, payment_method_id: str, set_as_default: bool
) -> PaymentMethod:
    pm = stripe.PaymentMethod.retrieve(payment_method_id)

    customer_id = await ensure_stripe_customer(db, user)
    if pm.customer is None:
        stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)
    elif pm.customer != customer_id:
        # Belongs to someone else's Stripe customer — never attach it here.
        raise PaymentMethodNotFound("This card is not associated with your account")

    card = pm.card
    masked_details = f"{card.brand.capitalize()} •••• {card.last4}"

    repo = PaymentMethodRepository(db)
    if set_as_default:
        await repo.unset_default_for_user(user.id)

    return await repo.create(
        user_id=user.id,
        provider=PaymentMethodProvider.stripe,
        type=PaymentMethodType.card,
        external_reference=payment_method_id,
        masked_details=masked_details,
        is_default=set_as_default,
    )


async def link_mpesa_number(
    db: AsyncSession, *, user: User, phone_number: str, set_as_default: bool
) -> PaymentMethod:
    try:
        normalized = normalize_kenyan_phone(phone_number)
    except ValueError as e:
        raise InvalidPhoneNumber(str(e))

    repo = PaymentMethodRepository(db)
    existing = await repo.list_for_user(user.id)
    if any(m.provider == PaymentMethodProvider.mpesa and m.external_reference == normalized for m in existing):
        raise DuplicatePaymentMethod(f"{phone_number} is already linked to your account")

    masked_details = f"M-Pesa •••• {normalized[-4:]}"

    if set_as_default:
        await repo.unset_default_for_user(user.id)

    return await repo.create(
        user_id=user.id,
        provider=PaymentMethodProvider.mpesa,
        type=PaymentMethodType.mobile_wallet,
        external_reference=normalized,
        masked_details=masked_details,
        is_default=set_as_default,
    )


async def delete_payment_method(db: AsyncSession, *, user: User, method_id) -> None:
    repo = PaymentMethodRepository(db)
    method = await repo.get_by_id_for_user(method_id, user.id)
    if method is None:
        raise PaymentMethodNotFound("Payment method not found")

    # Stripe cards are also detached from the Customer on Stripe's side,
    # so a deleted card here can't still be silently charged there.
    if method.provider == PaymentMethodProvider.stripe:
        try:
            stripe.PaymentMethod.detach(method.external_reference)
        except stripe.error.StripeError:
            # Already detached, or Stripe-side issue — the local record
            # is still the source of truth for what BridgePay considers
            # "linked", so proceed with deleting it regardless.
            pass

    await repo.delete(method)
