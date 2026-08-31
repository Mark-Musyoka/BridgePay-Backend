import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.limiter import limiter
from app.modules.accounts.router import router as accounts_router
from app.modules.admin.router import router as admin_router
from app.modules.auth.router import router as auth_router
from app.modules.transactions.router import router as transactions_router
from app.modules.transfers.router import router as transfers_router
from app.modules.users.router import router as users_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="BridgePay API",
    description="Learning-project payments platform backend.",
    version="0.1.0",
)

# Any localhost/127.0.0.1 port, http or https — covers `npm run dev` binding
# to whatever port is free, without needing a fixed allow-list for local dev.
# Scoped to loopback only, so this doesn't widen the surface the way a bare
# "*" would. Deployed frontend origins go in ALLOWED_ORIGINS instead.
LOCAL_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_origin_regex=LOCAL_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log the real exception server-side, but never echo its details back to
    # the client — a stack trace or exception message can leak internal
    # details (file paths, query fragments, library versions). The client
    # gets a generic message; the specifics stay in the server log.
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


API_PREFIX = "/api/v1"

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(users_router, prefix=API_PREFIX)
app.include_router(accounts_router, prefix=API_PREFIX)
app.include_router(transfers_router, prefix=API_PREFIX)
app.include_router(transactions_router, prefix=API_PREFIX)
app.include_router(admin_router, prefix=API_PREFIX)


@app.get("/")
async def health_check():
    """Basic liveness check — confirms the app boots and responds. Deliberately
    NOT under /api/v1: render.yaml's healthCheckPath and infra tooling generally
    expect an unversioned root health check."""
    return {
        "status": "ok",
        "service": "bridgepay-backend",
        "environment": settings.ENVIRONMENT,
    }
