# Uninstall Celery

Removes background tasks end to end: the app, the worker and beat
services, the task layer, and the jobs demo that exercises them
(`DemoJob`, the heartbeat, the jobs endpoints). Redis stays — it
backs the cache and rate limiting. **This removes a model: run the
migration reset afterwards.**

Precondition: the chat demo is already gone — it runs its turns on
the worker, which is why the interview keeps Celery whenever chat is
kept and why the chat-demo guide runs before this one.

If Elasticsearch was kept, `_queue_reindex` in
`clx/app/services/demo.py` still queues a task: rewire it to run
synchronously — `transaction.on_commit(demo_docket_reindex)` — so
the docket import keeps working without a worker. (If Elasticsearch
was dropped, the earlier guide already removed it.)

## Remove whole files

1. `clx/celery.py`.
2. The whole `clx/app/tasks/` package.
3. `clx/app/tests/test_tasks.py`.
4. `clx/app/templates/pages/demos/celery.html` and the Celery
   tile in `clx/app/templates/pages/demos/index.html`.

## Shared-file edits

5. `clx/app/services/demo.py`: delete `demo_heartbeat`,
   `demo_job_run`, `demo_job_run_batch`, `demo_job_cancel`,
   `demo_job_delete`, `demo_job_execute`, `_dispatch`, and the
   related constants (`MAX_DELAY_SECONDS`, `MAX_SUBTASKS`) and
   imports.
6. `clx/app/selectors/demo.py`: delete `demo_heartbeat_read`
   and `demo_job_list`, the `cache` and `DEMO_HEARTBEAT_CACHE_KEY`
   imports, and `DemoJob` from the models import.
7. `clx/app/models/demo.py`: delete `DemoJob` (and its
   re-export in `clx/app/models/__init__.py`).
8. `clx/app/api/demos.py`: delete `heartbeat`, `job_list`,
   `job_run`, `job_run_batch`, `job_cancel`, `job_delete`, `_job`,
   and `_iso`; in `clx/app/urls.py`, the `heartbeat/` and five
   `jobs/` entries in `demos_api_patterns` and the
   `path("celery/", ...)` entry in `demos_view_patterns`.
9. The `celery` view in `clx/app/views/demos.py`.
10. `clx/app/cache.py`: delete `DEMO_HEARTBEAT_CACHE_KEY`.
11. `clx/settings.py`: delete `CELERY_BROKER_URL`,
    `CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP`, and
    `CELERY_BEAT_SCHEDULE`.
12. `clx/app/services/health.py`: delete `check_celery`, the
    `"celery"` entries in `ServiceName` and `CHECKS`, and the
    module-level import of the celery app — this import is what
    breaks `/api/health/` the moment the package is gone, so it
    cannot be skipped.

## Compose, infra, dependencies

13. `docker-compose.yml`: the `celery` and `celery-beat` services.
14. `infra/__main__.py`: the celery worker and beat Deployments.
15. `pyproject.toml`: the `celery[redis]` dependency and the
    `celery-types` dev dependency (keep `redis` — the cache client
    needs it).

## Checks and explorer

16. `clx/app/selectors/codebase.py`: the module-level
    `from clx.celery import app as celery_app` import **must** go
    or `manage check` and the admin explorer crash the moment
    `clx/celery.py` is deleted — remove it along with
    `build_tasks`, `build_beat_entries`, and their calls in `build()`.
17. `clx/app/checks/imports.py`: the `"tasks"` rows of
    `LAYER_PACKAGES` and `ALLOWED_IMPORTS`, the `"tasks"` member of
    the `services` row, `"tasks"` in `DECLARED_APP_MODULES`, and
    `check_lazy_task_imports` (E104) with its wiring and test case.
18. `clx/app/checks/calls.py`: `check_tasks_queue_on_commit`
    (E602) with its wiring and test case, and `clx.app.tasks` in
    `READ_LAYERS`; `clx/app/checks/registers.py`:
    `check_task_names` (E202) likewise.
19. `cotton/admin/codebase/explorer.html`: the `task` and
    `beat-entry` rows of `CODEBASE_LAYERS`; the task tests in
    `clx/app/tests/test_codebase.py`.

## Tests

20. `clx/app/tests/test_demo.py`: delete the job and heartbeat
    tests; keep the tests that iterate `demos_view_patterns` — they
    adjust themselves.
21. `clx/app/tests/test_health.py`: delete the celery-specific
    tests.

Delete the "## Tasks" section of CLAUDE.md and prune its other
celery mentions (grep -i celery), then run the migration reset and
the verify suite.
