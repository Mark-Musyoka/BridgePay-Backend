from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import accounts, admin, auth, transactions, transfers, users
from app.core.config import settings
from app.core.limiter import limiter

app = FastAPI(
    title="BridgePay API",
    description="Learning-project payments platform backend.",
    version="0.1.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(accounts.router)
app.include_router(transfers.router)
app.include_router(transactions.router)
app.include_router(admin.router)


@app.get("/")
async def health_check():
    """Basic liveness check — confirms the app boots and responds."""
    return {
        "status": "ok",
        "service": "bridgepay-backend",
        "environment": settings.ENVIRONMENT,
    }
