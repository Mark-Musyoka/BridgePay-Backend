"""
Shared Stripe SDK configuration. Every module that talks to Stripe
(payment_methods, deposits, payouts) imports `stripe` from here rather
than configuring `stripe.api_key` itself in multiple places.
"""

import stripe

from app.core.config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

__all__ = ["stripe"]
