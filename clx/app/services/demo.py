import json
import logging
import random
import time
from collections.abc import Iterator
from datetime import date, timedelta
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any
from uuid import uuid4

from django.core.cache import cache
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone
from elasticsearch.helpers import bulk

from clx.app.cache import (
    DEMO_HEARTBEAT_CACHE_KEY,
)
from clx.app.exceptions import ApplicationError
from clx.app.models import (
    DemoAttorney,
    DemoDocket,
    DemoDocketEntry,
    DemoJob,
    DemoParty,
    DemoUpload,
    User,
)
from clx.app.search import (
    DEMO_DOCKET_MAPPING,
    demo_docket_document,
    demo_docket_index,
    search_client,
)

logger = logging.getLogger(__name__)

JOB_SLEEP_MIN_SECONDS = 2
JOB_SLEEP_MAX_SECONDS = 10
MAX_DELAY_SECONDS = 3600
MAX_SUBTASKS = 20
MAX_UPLOAD_FILES = 10
MAX_UPLOAD_SIZE = 10 * 1024 * 1024

PACKAGED_DOCKETS = files("clx") / "data" / "dockets.jsonl"

IMPORT_BATCH_SIZE = 1000
IMPORT_FLUSH_EVERY_DOCKETS = 200
REINDEX_CHUNK_SIZE = 200

DOCKET_TEXT_FIELDS = (
    "court_id",
    "pacer_case_id",
    "case_name",
    "docket_number",
    "assigned_to_str",
    "referred_to_str",
    "cause",
    "nature_of_suit",
    "jury_demand",
    "jurisdiction",
    "demand",
    "mdl_status",
    "ordered_by",
    "federal_defendant_number",
    "federal_dn_case_type",
    "federal_dn_office_code",
    "federal_dn_judge_initials_assigned",
    "federal_dn_judge_initials_referred",
)
DOCKET_DATE_FIELDS = (
    "date_filed",
    "date_terminated",
    "date_converted",
    "date_discharged",
)


def demo_heartbeat() -> None:
    """Record the current time in the cache."""
    cache.set(
        DEMO_HEARTBEAT_CACHE_KEY, timezone.now().isoformat(), timeout=None
    )


@transaction.atomic
def demo_job_run(*, user: User, delay_seconds: int = 0) -> DemoJob:
    """Create a demo job and queue it, optionally delayed."""
    if not 0 <= delay_seconds <= MAX_DELAY_SECONDS:
        raise ApplicationError(
            f"delay_seconds must be between 0 and {MAX_DELAY_SECONDS}"
        )
    job = DemoJob(
        user=user,
        name="Scheduled task" if delay_seconds else "Simple task",
        scheduled_for=(
            timezone.now() + timedelta(seconds=delay_seconds)
            if delay_seconds
            else None
        ),
    )
    job.full_clean()
    job.save()
    _dispatch(job, countdown=delay_seconds)
    return job


@transaction.atomic
def demo_job_run_batch(
    *, user: User, subtask_count: int, fail_rate: float = 0.0
) -> DemoJob:
    """Create a parent demo job fanned out into queued subtasks."""
    if not 1 <= subtask_count <= MAX_SUBTASKS:
        raise ApplicationError(
            f"subtask_count must be between 1 and {MAX_SUBTASKS}"
        )
    if not 0 <= fail_rate <= 1:
        raise ApplicationError("fail_rate must be between 0 and 1")
    parent = DemoJob(
        user=user, name=f"Batch of {subtask_count}", fail_rate=fail_rate
    )
    parent.full_clean()
    parent.save()
    for index in range(subtask_count):
        child = DemoJob(
            user=user,
            parent=parent,
            name=f"Subtask {index + 1}",
            fail_rate=fail_rate,
        )
        child.full_clean()
        child.save()
        _dispatch(child, countdown=0)
    return parent


def demo_job_cancel(*, user: User, job_id: str) -> DemoJob:
    """Cancel a running demo job; the worker's finish becomes a no-op."""
    job = DemoJob.objects.filter(id=job_id, user=user).first()
    if job is None:
        raise ApplicationError("Job not found")
    updated = DemoJob.objects.filter(
        id=job.id, status=DemoJob.Status.RUNNING
    ).update(status=DemoJob.Status.CANCELLED, finished_at=timezone.now())
    if not updated:
        raise ApplicationError("Only a running job can be cancelled")
    job.refresh_from_db()
    return job


def demo_job_delete(*, user: User, job_id: str) -> None:
    """Delete a demo job and its subtasks; in-flight tasks find nothing."""
    job = DemoJob.objects.filter(id=job_id, user=user).first()
    if job is None:
        raise ApplicationError("Job not found")
    job.delete()


def demo_job_execute(job_id: str) -> None:
    """Run one demo job: sleep, record progress, and roll up to the parent."""
    job = DemoJob.objects.filter(id=job_id).first()
    if job is None:
        return
    now = timezone.now()
    active = [DemoJob.Status.PENDING, DemoJob.Status.RUNNING]
    started = DemoJob.objects.filter(
        id=job.id, status=DemoJob.Status.PENDING
    ).update(status=DemoJob.Status.RUNNING, started_at=now)
    if not started:
        return
    if job.parent_id:
        DemoJob.objects.filter(
            id=job.parent_id, status=DemoJob.Status.PENDING
        ).update(status=DemoJob.Status.RUNNING, started_at=now)
    time.sleep(random.uniform(JOB_SLEEP_MIN_SECONDS, JOB_SLEEP_MAX_SECONDS))
    failed = job.fail_rate > 0 and random.random() < job.fail_rate
    DemoJob.objects.filter(id=job.id, status=DemoJob.Status.RUNNING).update(
        status=(DemoJob.Status.FAILED if failed else DemoJob.Status.SUCCEEDED),
        finished_at=timezone.now(),
    )
    if job.parent_id:
        siblings = DemoJob.objects.filter(parent_id=job.parent_id)
        if not siblings.filter(status__in=active).exists():
            if not siblings.exclude(status=DemoJob.Status.SUCCEEDED).exists():
                final = DemoJob.Status.SUCCEEDED
            elif siblings.filter(status=DemoJob.Status.FAILED).exists():
                final = DemoJob.Status.FAILED
            else:
                final = DemoJob.Status.CANCELLED
            DemoJob.objects.filter(id=job.parent_id, status__in=active).update(
                status=final, finished_at=timezone.now()
            )


@transaction.atomic
def demo_upload_create_batch(
    *, user: User, files: list[UploadedFile]
) -> list[DemoUpload]:
    """Store a batch of uploaded files under user id / file id / filename."""
    if not files:
        raise ApplicationError("No files were sent")
    if len(files) > MAX_UPLOAD_FILES:
        raise ApplicationError(
            f"Too many files: at most {MAX_UPLOAD_FILES} per upload"
        )
    for file in files:
        if (file.size or 0) > MAX_UPLOAD_SIZE:
            raise ApplicationError(
                f'"{file.name}" is larger than '
                f"{MAX_UPLOAD_SIZE // (1024 * 1024)} MB"
            )
    uploads = []
    for file in files:
        upload = DemoUpload(
            user=user,
            file=file,
            name=file.name or "unnamed",
            size=file.size or 0,
            content_type=file.content_type or "",
        )
        upload.full_clean()
        upload.save()
        uploads.append(upload)
    return uploads


def demo_upload_delete(*, user: User, upload_id: str) -> None:
    """Delete an upload's row and its stored file."""
    upload = DemoUpload.objects.filter(id=upload_id, user=user).first()
    if upload is None:
        raise ApplicationError("Upload not found")
    upload.delete()
    upload.file.delete(save=False)


def _text(record: dict[str, Any], key: str) -> str:
    return record.get(key) or ""


def _date(value: Any) -> date | None:
    return date.fromisoformat(value) if value else None


@transaction.atomic
def demo_docket_import(
    source: Traversable = PACKAGED_DOCKETS,
) -> dict[str, int]:
    """Drop the demo docket tables and reimport the source from scratch."""
    DemoDocket.objects.all().delete()

    counts = dict.fromkeys(("dockets", "entries", "parties", "attorneys"), 0)
    dockets: list[DemoDocket] = []
    entries: list[DemoDocketEntry] = []
    parties: list[DemoParty] = []
    attorneys: list[DemoAttorney] = []

    def flush() -> None:
        DemoDocket.objects.bulk_create(dockets, batch_size=IMPORT_BATCH_SIZE)
        DemoParty.objects.bulk_create(parties, batch_size=IMPORT_BATCH_SIZE)
        DemoDocketEntry.objects.bulk_create(
            entries, batch_size=IMPORT_BATCH_SIZE
        )
        DemoAttorney.objects.bulk_create(
            attorneys, batch_size=IMPORT_BATCH_SIZE
        )
        counts["dockets"] += len(dockets)
        counts["parties"] += len(parties)
        counts["entries"] += len(entries)
        counts["attorneys"] += len(attorneys)
        dockets.clear()
        parties.clear()
        entries.clear()
        attorneys.clear()

    with source.open() as lines:
        for line in lines:
            record = json.loads(line)
            docket = DemoDocket(
                docket_id=record["docket_id"],
                **{f: _text(record, f) for f in DOCKET_TEXT_FIELDS},
                **{f: _date(record.get(f)) for f in DOCKET_DATE_FIELDS},
            )
            dockets.append(docket)
            for entry in record.get("docket_entries") or []:
                entries.append(
                    DemoDocketEntry(
                        docket=docket,
                        date_filed=date.fromisoformat(entry["date_filed"]),
                        date_entered=_date(entry.get("date_entered")),
                        document_number=_text(entry, "document_number"),
                        pacer_doc_id=_text(entry, "pacer_doc_id"),
                        pacer_seq_no=_text(entry, "pacer_seq_no"),
                        description=_text(entry, "description"),
                    )
                )
            for record_party in record.get("parties") or []:
                party = DemoParty(
                    docket=docket,
                    name=_text(record_party, "name"),
                    type=_text(record_party, "type"),
                    extra_info=_text(record_party, "extra_info"),
                    date_terminated=_date(record_party.get("date_terminated")),
                )
                parties.append(party)
                for record_attorney in record_party.get("attorneys") or []:
                    attorneys.append(
                        DemoAttorney(
                            party=party,
                            name=_text(record_attorney, "name"),
                            contact=_text(record_attorney, "contact"),
                            roles=record_attorney.get("roles") or [],
                        )
                    )
            if len(dockets) >= IMPORT_FLUSH_EVERY_DOCKETS:
                flush()
    flush()
    _queue_reindex()
    return counts


def _queue_reindex() -> None:
    """Queue the reindex task after the surrounding import commits."""
    from clx.app.tasks import demo_docket_reindex_task

    transaction.on_commit(lambda: demo_docket_reindex_task.delay())


def demo_docket_reindex() -> int:
    """Rebuild the demo dockets index from postgres and swap the alias to it."""
    client = search_client()
    alias = demo_docket_index()
    physical = f"{alias}-{uuid4().hex[:12]}"
    client.indices.create(index=physical, mappings=DEMO_DOCKET_MAPPING)

    def actions() -> Iterator[dict[str, Any]]:
        dockets = DemoDocket.objects.prefetch_related(
            "entries", "parties__attorneys"
        ).iterator(chunk_size=REINDEX_CHUNK_SIZE)
        for docket in dockets:
            yield {
                "_index": physical,
                "_id": docket.docket_id,
                **demo_docket_document(docket),
            }

    count, _ = bulk(client, actions())
    stale = [
        name
        for name in client.indices.get(index=f"{alias}-*")
        if name != physical
    ]
    client.indices.update_aliases(
        actions=[
            {"add": {"index": physical, "alias": alias}},
            *({"remove_index": {"index": name}} for name in stale),
        ]
    )
    client.indices.refresh(index=alias)
    return count


def _dispatch(job: DemoJob, *, countdown: int) -> None:
    """Queue the execute task for a job after the surrounding commit."""
    from clx.app.tasks import demo_job_execute_task

    if countdown:
        transaction.on_commit(
            lambda: demo_job_execute_task.apply_async(
                args=(str(job.id),), countdown=float(countdown)
            )
        )
    else:
        transaction.on_commit(lambda: demo_job_execute_task.delay(str(job.id)))
