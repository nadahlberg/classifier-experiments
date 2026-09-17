from django.conf import settings

import clx.app.tasks  # noqa: F401
from clx.celery import app as celery_app


def test_every_beat_schedule_entry_names_a_registered_task() -> None:
    """Beat resolves task names at send time, not at startup.

    A CELERY_BEAT_SCHEDULE entry pointing at a renamed or deleted task
    does not crash beat — it sends the message anyway, the worker logs
    "Received unregistered task" and drops it, and the work silently
    never runs. Importing the tasks module registers every task, so any
    scheduled name missing from the registry here is a schedule entry
    that can never fire.
    """
    for entry in settings.CELERY_BEAT_SCHEDULE.values():
        assert entry["task"] in celery_app.tasks
