from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost/bridgepay"

    JWT_SECRET_KEY: str = "dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    ENVIRONMENT: str = "development"

    # Comma-separated list of allowed origins for the deployed frontend
    # (e.g. "https://bridgepay-frontend.vercel.app"). Local dev origins
    # (localhost/127.0.0.1, any port) are always allowed separately — see
    # main.py — so they don't need to be listed here.
    ALLOWED_ORIGINS: str = ""

    # --- Stripe (card deposits, card payouts) ---
    # Get these from https://dashboard.stripe.com/test/apikeys (test mode
    # keys start with sk_test_/pk_test_ — use those for everything until
    # this is genuinely ready for real money).
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    # From the webhook endpoint's settings in the Stripe dashboard, used
    # to verify incoming webhook signatures (see modules/webhooks).
    STRIPE_WEBHOOK_SECRET: str = ""

    # --- M-Pesa Daraja (STK Push deposits, B2C payouts) ---
    # Get these from https://developer.safaricom.co.ke — sandbox
    # credentials are free and instant; production requires a Safaricom
    # business application/approval process.
    MPESA_ENV: str = "sandbox"  # "sandbox" or "production"
    MPESA_CONSUMER_KEY: str = ""
    MPESA_CONSUMER_SECRET: str = ""
    MPESA_SHORTCODE: str = ""  # Paybill/till number (STK Push deposits)
    MPESA_PASSKEY: str = ""  # Lipa Na M-Pesa Online passkey
    MPESA_INITIATOR_NAME: str = ""  # B2C payouts
    MPESA_INITIATOR_PASSWORD: str = ""  # B2C payouts (encrypted with the cert Safaricom provides)
    MPESA_CALLBACK_BASE_URL: str = ""  # this app's own public URL, e.g. https://bridgepay-backend.onrender.com

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]


settings = Settings()
