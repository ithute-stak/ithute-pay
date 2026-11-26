from workers.celery_app import celery_app


SCHEDULED_TASKS = {
    "workers.tasks.retry_due_webhooks",
    "workers.tasks.recover_processing_transactions",
    "workers.tasks.process_settlement_instructions",
    "workers.tasks.recover_direct_funding_payouts",
}


def test_worker_imports_task_module_before_consuming() -> None:
    assert "workers.tasks" in celery_app.conf.include

    # This is the same default-module import path Celery executes when a worker
    # starts from `-A workers.celery_app.celery_app`.
    celery_app.loader.import_default_modules()

    registered = set(celery_app.tasks.keys())
    assert SCHEDULED_TASKS <= registered
    assert "workers.tasks.deliver_webhook" in registered


def test_every_beat_schedule_entry_points_to_a_registered_task() -> None:
    celery_app.loader.import_default_modules()

    scheduled = {
        entry["task"]
        for entry in celery_app.conf.beat_schedule.values()
    }
    registered = set(celery_app.tasks.keys())

    assert scheduled == SCHEDULED_TASKS
    assert scheduled <= registered


def test_retired_provider_worker_not_registered_or_scheduled() -> None:
    celery_app.loader.import_default_modules()
    assert "workers.tasks.reconcile_golink_callbacks" not in celery_app.tasks
    assert all("golink" not in entry["task"] for entry in celery_app.conf.beat_schedule.values())
