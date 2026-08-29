from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(
    title="BridgePay API",
    description="Learning-project payments platform backend.",
    version="0.1.0",
)


@app.get("/")
async def health_check():
    """Basic liveness check — confirms the app boots and responds."""
    return {
        "status": "ok",
        "service": "bridgepay-backend",
        "environment": settings.ENVIRONMENT,
    }
