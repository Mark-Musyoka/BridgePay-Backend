"""
Admin doesn't define any response shapes of its own — both endpoints
return exactly the shape their owning module already defines
(transactions, audit). Re-exporting here means the router only ever
imports from `app.modules.admin.schemas`, not from two unrelated
modules directly, without duplicating either schema.
"""

from app.modules.audit.schemas import AuditLogListResponse
from app.modules.transactions.schemas import TransactionListResponse

__all__ = ["TransactionListResponse", "AuditLogListResponse"]
