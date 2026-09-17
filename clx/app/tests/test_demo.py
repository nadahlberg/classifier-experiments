from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from clx.app.exceptions import ApplicationError
from clx.app.models import DemoJob, User
from clx.app.services import demo as demo_service
from clx.app.services.user import user_create
from clx.app.urls import demos_view_patterns


@pytest.fixture
def user() -> User:
    return user_create(email="runner@example.com")


@pytest.mark.django_db
def test_batch_parent_succeeds_only_when_the_last_subtask_finishes(
    monkeypatch: pytest.MonkeyPatch, user: User
) -> None:
    """The parent job has no Celery task of its own — each subtask rolls its
    completion up, and whichever subtask finishes last marks the parent done.

    If the roll-up check ever counted wrong (e.g. only looked at the finishing
    subtask instead of all siblings), the parent would flip to succeeded while
    subtasks were still running, and the demo page would show a finished batch
    with children still churning. Executing subtasks one at a time pins the
    transition to exactly the last one.
    """
    monkeypatch.setattr(
        "clx.app.services.demo.time.sleep", lambda seconds: None
    )
    parent = demo_service.demo_job_run_batch(user=user, subtask_count=3)
    children = list(parent.children.order_by("created_at"))

    demo_service.demo_job_execute(str(children[0].id))
    parent.refresh_from_db()
    assert parent.status == DemoJob.Status.RUNNING

    demo_service.demo_job_execute(str(children[1].id))
    parent.refresh_from_db()
    assert parent.status == DemoJob.Status.RUNNING

    demo_service.demo_job_execute(str(children[2].id))
    parent.refresh_from_db()
    assert parent.status == DemoJob.Status.SUCCEEDED
    assert parent.finished_at is not None


@pytest.mark.django_db
def test_execute_does_nothing_when_the_job_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task arguments cross the broker as JSON, so by the time the worker
    picks a job up the row may have been deleted. The task re-fetches and
    must silently do nothing rather than raise — a crash here would send the
    task to retry against a row that will never come back.
    """
    monkeypatch.setattr(
        "clx.app.services.demo.time.sleep", lambda seconds: None
    )

    demo_service.demo_job_execute("00000000-0000-0000-0000-000000000000")


@pytest.mark.django_db
def test_job_list_api_returns_only_the_callers_jobs(user: User) -> None:
    """Jobs are user-scoped: the list endpoint filters by request.user, so
    two users firing demo jobs never see each other's rows. This fails if the
    selector ever drops the user filter.
    """
    other = user_create(email="other@example.com")
    demo_service.demo_job_run(user=user)
    demo_service.demo_job_run_batch(user=other, subtask_count=2)

    client = Client()
    client.force_login(user)
    payload = client.get("/api/demos/jobs/", secure=True).json()

    assert [job["name"] for job in payload["jobs"]] == ["Simple task"]

    anonymous = Client().get("/api/demos/jobs/", secure=True)
    assert anonymous.status_code == 401


@pytest.mark.django_db
def test_run_endpoints_create_the_expected_rows(user: User) -> None:
    """The run endpoint records a scheduled_for only when delayed, and the
    batch endpoint creates the parent plus exactly subtask_count children,
    all pending until a worker picks them up.
    """
    client = Client()
    client.force_login(user)

    simple = client.post(
        "/api/demos/jobs/run/",
        "{}",
        content_type="application/json",
        secure=True,
    ).json()
    assert simple["scheduled_for"] is None

    scheduled = client.post(
        "/api/demos/jobs/run/",
        '{"delay_seconds": 60}',
        content_type="application/json",
        secure=True,
    ).json()
    assert scheduled["scheduled_for"] is not None

    batch = client.post(
        "/api/demos/jobs/run-batch/",
        '{"subtask_count": 4}',
        content_type="application/json",
        secure=True,
    ).json()
    parent = DemoJob.objects.get(id=batch["id"])
    assert parent.children.count() == 4
    assert not parent.children.exclude(status=DemoJob.Status.PENDING).exists()


@pytest.mark.django_db
def test_out_of_bounds_inputs_are_rejected(user: User) -> None:
    """Bounds live in the service, so every interface shares them: a demo
    page should not be able to schedule a job a year out or fan out a
    thousand subtasks against the real broker.
    """
    with pytest.raises(ApplicationError):
        demo_service.demo_job_run(user=user, delay_seconds=-1)
    with pytest.raises(ApplicationError):
        demo_service.demo_job_run(user=user, delay_seconds=3601)
    with pytest.raises(ApplicationError):
        demo_service.demo_job_run_batch(user=user, subtask_count=0)
    with pytest.raises(ApplicationError):
        demo_service.demo_job_run_batch(user=user, subtask_count=21)
    with pytest.raises(ApplicationError):
        demo_service.demo_job_run_batch(
            user=user, subtask_count=2, fail_rate=-0.1
        )
    with pytest.raises(ApplicationError):
        demo_service.demo_job_run_batch(
            user=user, subtask_count=2, fail_rate=1.1
        )


@pytest.mark.django_db
def test_cancel_during_the_sleep_is_not_overwritten_by_the_worker(
    monkeypatch: pytest.MonkeyPatch, user: User
) -> None:
    """Cancelling never reaches into the worker — it just flips the row to
    cancelled. The worker's completion step only moves running jobs to
    succeeded, so a cancel that lands mid-sleep must survive the worker
    waking up and finishing.

    The sleep stub cancels the job, simulating a user clicking cancel while
    the worker is inside time.sleep. If execute's completion step were an
    unconditional write, this test would end with the job succeeded and the
    cancel silently lost.
    """
    job = demo_service.demo_job_run(user=user)
    monkeypatch.setattr(
        "clx.app.services.demo.time.sleep",
        lambda seconds: demo_service.demo_job_cancel(
            user=user, job_id=str(job.id)
        ),
    )

    demo_service.demo_job_execute(str(job.id))

    job.refresh_from_db()
    assert job.status == DemoJob.Status.CANCELLED
    assert job.finished_at is not None


@pytest.mark.django_db
def test_cancel_is_only_allowed_while_running(user: User) -> None:
    """Pending jobs have not started and finished jobs cannot be un-finished,
    so cancel rejects everything except a running job rather than quietly
    rewriting history.
    """
    job = demo_service.demo_job_run(user=user)
    with pytest.raises(ApplicationError):
        demo_service.demo_job_cancel(user=user, job_id=str(job.id))

    DemoJob.objects.filter(id=job.id).update(status=DemoJob.Status.RUNNING)
    cancelled = demo_service.demo_job_cancel(user=user, job_id=str(job.id))
    assert cancelled.status == DemoJob.Status.CANCELLED


@pytest.mark.django_db
def test_a_cancelled_subtask_completes_the_parent_as_cancelled(
    monkeypatch: pytest.MonkeyPatch, user: User
) -> None:
    """A parent finishes when no children are left pending or running, and
    it only reads succeeded if every child succeeded — a mixed batch is
    marked cancelled so the list does not claim clean success.
    """
    monkeypatch.setattr(
        "clx.app.services.demo.time.sleep", lambda seconds: None
    )
    parent = demo_service.demo_job_run_batch(user=user, subtask_count=2)
    first, second = parent.children.order_by("created_at")

    demo_service.demo_job_execute(str(first.id))

    monkeypatch.setattr(
        "clx.app.services.demo.time.sleep",
        lambda seconds: demo_service.demo_job_cancel(
            user=user, job_id=str(second.id)
        ),
    )
    demo_service.demo_job_execute(str(second.id))
    parent.refresh_from_db()
    assert parent.status == DemoJob.Status.CANCELLED
    assert parent.finished_at is not None


@pytest.mark.django_db
def test_a_failed_subtask_propagates_failure_to_the_parent(
    monkeypatch: pytest.MonkeyPatch, user: User
) -> None:
    """fail_rate=1 makes every subtask fail deterministically (random() is
    always < 1), so this pins the propagation rule without flakiness: a
    parent whose children finished with any failure ends failed, not
    succeeded — and failure outranks cancelled in the roll-up so a broken
    batch is never reported as merely cancelled.
    """
    monkeypatch.setattr(
        "clx.app.services.demo.time.sleep", lambda seconds: None
    )
    parent = demo_service.demo_job_run_batch(
        user=user, subtask_count=2, fail_rate=1
    )
    for child in parent.children.order_by("created_at"):
        demo_service.demo_job_execute(str(child.id))

    parent.refresh_from_db()
    assert parent.status == DemoJob.Status.FAILED
    assert not parent.children.exclude(status=DemoJob.Status.FAILED).exists()


@pytest.mark.django_db
def test_delete_removes_the_row_its_subtasks_and_nothing_of_others(
    user: User,
) -> None:
    """Delete cascades to subtasks through the parent FK and is scoped to
    the caller, so one user cannot delete another's jobs even with a valid
    id.
    """
    parent = demo_service.demo_job_run_batch(user=user, subtask_count=2)
    other = user_create(email="deleter@example.com")
    with pytest.raises(ApplicationError):
        demo_service.demo_job_delete(user=other, job_id=str(parent.id))

    demo_service.demo_job_delete(user=user, job_id=str(parent.id))
    assert not DemoJob.objects.exists()


@pytest.mark.django_db
def test_heartbeat_endpoint_reads_back_what_the_task_stored(
    settings: Any, user: User
) -> None:
    """The beat-scheduled heartbeat writes an ISO timestamp to the cache and
    the endpoint returns it verbatim, so the page can show when beat last
    fired. Uses a local-memory cache so the test does not depend on redis.
    """
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    client = Client()
    client.force_login(user)

    empty = client.get("/api/demos/heartbeat/", secure=True).json()
    assert empty["last_run"] is None

    demo_service.demo_heartbeat()
    stored = client.get("/api/demos/heartbeat/", secure=True).json()
    assert stored["last_run"] is not None


@pytest.mark.django_db
def test_celery_demo_page_requires_login(user: User) -> None:
    """The demo pages are all behind the login wall, so an anonymous visitor
    must be bounced to sign-in instead of rendering. This one is also
    user-scoped — the jobs it lists belong to the signed-in user.
    """
    client = Client()
    anonymous = client.get("/demos/celery/", secure=True)
    assert anonymous.status_code == 302

    client.force_login(user)
    page = client.get("/demos/celery/", secure=True)
    assert page.status_code == 200
    assert b"Batch task" in page.content


@pytest.mark.django_db
def test_every_demo_page_is_behind_the_login_wall() -> None:
    """The demos are the tour of the codebase for someone who has signed in,
    and several of them read and write that user's own rows, so none of them
    belong to the public site.

    The list is the demos surface's own pattern list rather than written
    out, so a new demo page is covered the moment it is routed instead of
    whenever someone remembers to add it here — and unlike the old
    startswith("demos-") filter, that includes the landing page.
    """
    client = Client()

    assert demos_view_patterns
    for pattern in demos_view_patterns:
        response = client.get(reverse(pattern.name), secure=True)
        assert response.status_code == 302, pattern.name
