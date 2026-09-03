from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Keyed by client IP. Backed by Redis (reusing the same instance Celery
# already needs) rather than in-memory storage, so limits are enforced
# correctly across multiple app instances/workers, and survive a restart
# instead of silently resetting.
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.CELERY_BROKER_URL)
