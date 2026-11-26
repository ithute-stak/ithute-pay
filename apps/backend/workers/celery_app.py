from celery import Celery
from database.config.config import settings

celery_app = Celery(
    "paybridge", broker=settings.REDIS_URL, backend=settings.REDIS_URL,
    include=["workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json", result_serializer="json", accept_content=["json"],
    timezone="UTC", enable_utc=True,
    beat_schedule={
        "retry-webhooks-every-minute":{"task":"workers.tasks.retry_due_webhooks","schedule":60.0},
        "recover-processing-transactions":{"task":"workers.tasks.recover_processing_transactions","schedule":60.0},
        "process-settlement-instructions":{"task":"workers.tasks.process_settlement_instructions","schedule":30.0},
        "recover-direct-funding-payouts":{"task":"workers.tasks.recover_direct_funding_payouts","schedule":30.0},
    },
)
