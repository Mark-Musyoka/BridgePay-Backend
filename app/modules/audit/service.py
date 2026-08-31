import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog


async def log_action(
    db: AsyncSession,
    *,
    request: Request,
    action: str,
    user_id: uuid.UUID | None = None,
    detail: str | None = None,
) -> None:
    """Write an audit log entry. Caller is responsible for committing —
    this just adds the row to the current session so it lands in the same
    DB transaction as the action it's recording."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        detail=detail,
        ip_address=request.client.host if request.client else None,
    )
    db.add(entry)
