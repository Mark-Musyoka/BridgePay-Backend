import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # ISO 3166-1 alpha-2 code (e.g. "KE", "US") — see app/core/countries.py.
    # Nullable so existing pre-country-field accounts aren't broken by the
    # migration; new registrations require it (enforced in UserCreate).
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # Lazily created on first Stripe interaction (SetupIntent/PaymentIntent) —
    # see app/modules/payment_methods/service.py. Nullable since most users
    # will never touch Stripe at all (e.g. M-Pesa-only users in Kenya).
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
