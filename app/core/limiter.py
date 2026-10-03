from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Keyed by client IP. Backed by Redis (reusing the same instance Celery
# already needs) rather than in-memory storage, so limits are enforced
# correctly across multiple app instances/workers, and survive a restart
# instead of silently resetting.
#
# swallow_errors=True: if Redis is unreachable or misconfigured (wrong
# password, network hiccup, etc.), slowapi logs it and lets the request
# through instead of raising — rate limiting becomes a no-op for that
# request rather than taking down every endpoint it guards (previously:
# auth/register, auth/login) with an unrelated 500. Rate limiting is a
# defense-in-depth feature; it should degrade, not become a hard
# dependency for the features it's protecting.
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.CELERY_BROKER_URL, swallow_errors=True)
