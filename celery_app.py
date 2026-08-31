from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "bridgepay",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

# Explicit import (rather than autodiscover_tasks, which expects a
# Django-style app registry) so tasks are reliably registered.
from app.modules.auth import tasks as auth_tasks  # noqa: E402,F401
from app.modules.transfers import tasks as transfer_tasks  # noqa: E402,F401
