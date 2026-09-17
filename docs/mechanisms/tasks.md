# Background tasks

Celery with redis as the broker. [The app in
`starter/celery.py`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/celery.py#L7) is what `celery -A starter`
resolves to: it reads every `CELERY_*` setting from Django settings and
calls `autodiscover_tasks()`, which imports each installed app's `tasks`
package by name. Registration happens at import, so a task module
`tasks/__init__.py` does not import silently does not exist — which is why
[the `__all__` re-export list](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tasks/__init__.py#L9-L15) doubles as the registry
of what exists.

[`CELERY_BROKER_URL`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L189) is the same
`REDIS_URL` the cache uses, and
[`CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L190) keeps a
worker that boots before redis retrying instead of dying. The worker and
beat each run as their own service — in compose and in the cluster — off
the same image as the web process.

## Tasks are interfaces

A task calls one service and holds no logic of its own. All five current
tasks are in `tasks/demo.py`, each a one-line body:
[`demo_heartbeat_task`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tasks/demo.py#L6-L7),
[`demo_job_execute_task`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tasks/demo.py#L11-L12),
[`demo_docket_reindex_task`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tasks/demo.py#L16-L17),
[`demo_chat_turn_run_task`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tasks/demo.py#L21-L22) and
[`demo_chat_thread_title_generate_task`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tasks/demo.py#L26-L27). Arguments
cross the broker as JSON, so tasks receive ids, never objects, and the
service re-fetches — doing nothing if the row is gone, since the queue
can outlive the data.

Services queue tasks with `transaction.on_commit(lambda: task.delay(...))`,
never before the write commits (rules E104 and E602): a worker is fast
enough to pick up a job before the transaction that created its row
lands, and would then process a row it cannot see.

## The beat schedule

Periodic work is a [`CELERY_BEAT_SCHEDULE`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L191-L196) entry naming
the task by full dotted path
(`starter.app.tasks.demo.demo_heartbeat_task`, every 30 seconds). Beat
resolves that name at send time, not startup: an entry pointing at a
renamed or deleted task does not crash beat — the worker logs "Received
unregistered task" and drops it, and the work silently never runs.
[The guard test](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_tasks.py#L7-L18) imports the tasks package and asserts
every scheduled name is in the celery app's registry, so a stale entry
fails CI instead of failing silently in production.
