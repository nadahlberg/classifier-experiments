# Background tasks

Celery with redis as the broker. [The app in
`starter/celery.py`](sym:874e6777606f) is what `celery -A starter`
resolves to: it reads every `CELERY_*` setting from Django settings and
calls `autodiscover_tasks()`, which imports each installed app's `tasks`
package by name. Registration happens at import, so a task module
`tasks/__init__.py` does not import silently does not exist — which is why
[the `__all__` re-export list](sym:a910c6770a7f) doubles as the registry
of what exists.

[`CELERY_BROKER_URL`](sym:237046cd2fe6,4f556e1b9fef) is the same
`REDIS_URL` the cache uses, and
[`CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP`](sym:3001d47282c4) keeps a
worker that boots before redis retrying instead of dying. The worker and
beat each run as their own service — in compose and in the cluster — off
the same image as the web process.

## Tasks are interfaces

A task calls one service and holds no logic of its own. All five current
tasks are in `tasks/demo.py`, each a one-line body:
[`demo_heartbeat_task`](sym:7c2c4d1aee3c+),
[`demo_job_execute_task`](sym:16a5c4d90fcf+),
[`demo_docket_reindex_task`](sym:18c8ab5e669b+),
[`demo_chat_turn_run_task`](sym:cd60c7684812+) and
[`demo_chat_thread_title_generate_task`](sym:e4dd9dfa6fe8+). Arguments
cross the broker as JSON, so tasks receive ids, never objects, and the
service re-fetches — doing nothing if the row is gone, since the queue
can outlive the data.

Services queue tasks with `transaction.on_commit(lambda: task.delay(...))`,
never before the write commits (rules E104 and E602): a worker is fast
enough to pick up a job before the transaction that created its row
lands, and would then process a row it cannot see.

## The beat schedule

Periodic work is a [`CELERY_BEAT_SCHEDULE`](sym:ac037e9dc988) entry naming
the task by full dotted path
(`starter.app.tasks.demo.demo_heartbeat_task`, every 30 seconds). Beat
resolves that name at send time, not startup: an entry pointing at a
renamed or deleted task does not crash beat — the worker logs "Received
unregistered task" and drops it, and the work silently never runs.
[The guard test](sym:bed6dbecc645) imports the tasks package and asserts
every scheduled name is in the celery app's registry, so a stale entry
fails CI instead of failing silently in production.
