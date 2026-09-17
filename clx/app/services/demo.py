import json
import logging
import random
import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from functools import lru_cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any
from uuid import UUID, uuid4

import litellm
import redis
from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from elasticsearch.helpers import bulk

from clx.app.agents import AGENTS, Agent, ToolOutput
from clx.app.cache import (
    DEMO_CHAT_CANCEL_CACHE_TTL,
    DEMO_HEARTBEAT_CACHE_KEY,
    demo_chat_cancel_cache_key,
    demo_chat_events_channel,
)
from clx.app.exceptions import ApplicationError
from clx.app.models import (
    DemoAttorney,
    DemoChatMessage,
    DemoChatThread,
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
from clx.app.selectors.demo import (
    demo_chat_message_serialize,
    demo_chat_state_render,
    demo_chat_thread_context_tokens,
    demo_chat_thread_usage,
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


TITLE_MODEL = "openai/gpt-5.6-luna"
TITLE_PROMPT = (
    "Write a very short title (at most 6 words) for a conversation that "
    "opens with the user message you are given. Return only the title - "
    "no quotes, no trailing punctuation."
)
TITLE_INPUT_MAX_CHARS = 2000
TITLE_FALLBACK_MAX_CHARS = 60

COMPACTION_MODEL = "openai/gpt-5.6-luna"
COMPACTION_PROMPT = (
    "You are compacting a conversation so it can continue with less "
    "context. Summarize everything above the final instruction, keeping "
    "every fact, name, number, decision, and open question a later turn "
    "could need. Write compact prose, no preamble."
)
COMPACTION_INSTRUCTION = "Now write the summary."

FLUSH_INTERVAL_SECONDS = 0.5
TURN_STALE_SECONDS = 60 * 10


class _TurnLost(Exception):
    """Raised when another turn has claimed the thread mid-flight."""


def demo_chat_message_create(
    *,
    thread: DemoChatThread,
    data: dict[str, Any],
    kind: str = DemoChatMessage.Kind.CHAT,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost: float = 0.0,
) -> DemoChatMessage:
    """Persist one message row on a thread."""
    message = DemoChatMessage(
        thread=thread,
        kind=kind,
        data=data,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost,
    )
    message.full_clean()
    message.save()
    return message


@transaction.atomic
def demo_chat_message_send(
    *,
    user: User,
    message: str,
    agent: str = "",
    thread_id: str | None = None,
) -> DemoChatThread:
    """Append a user message and queue the agent's turn."""
    text = message.strip()
    if not text:
        raise ApplicationError("Message must not be empty")
    if thread_id:
        thread = DemoChatThread.objects.filter(id=thread_id, user=user).first()
        if thread is None:
            raise ApplicationError("Thread not found")
        created = False
    else:
        if agent not in AGENTS:
            raise ApplicationError("Unknown agent")
        thread = DemoChatThread(user=user, agent=agent)
        thread.full_clean()
        thread.save()
        created = True
    now = timezone.now()
    open_statuses = (DemoChatThread.Status.IDLE, DemoChatThread.Status.FAILED)
    turn = uuid4()
    claimed = DemoChatThread.objects.filter(
        Q(status__in=open_statuses) | Q(touched_at__lt=_stale_cutoff()),
        id=thread.id,
    ).update(
        status=DemoChatThread.Status.PENDING,
        turn=turn,
        touched_at=now,
        updated_at=now,
    )
    if not claimed:
        raise ApplicationError("A response is already in progress")
    thread.status = DemoChatThread.Status.PENDING
    thread.turn = turn
    thread.touched_at = now
    thread.updated_at = now
    row = demo_chat_message_create(
        thread=thread, data={"role": "user", "content": text}
    )
    cache.delete(demo_chat_cancel_cache_key(str(thread.id)))
    transaction.on_commit(lambda: _publish_message(thread, row, None))
    _queue_turn(thread)
    if created:
        _queue_title(thread)
    return thread


def demo_chat_turn_run(thread_id: str) -> None:
    """Run one agent turn, streaming and persisting as it goes."""
    thread = DemoChatThread.objects.filter(id=thread_id).first()
    if thread is None:
        return
    turn = uuid4()
    claimed = DemoChatThread.objects.filter(
        id=thread.id, status=DemoChatThread.Status.PENDING
    ).update(
        status=DemoChatThread.Status.RUNNING,
        turn=turn,
        touched_at=timezone.now(),
    )
    if not claimed:
        return
    thread.turn = turn
    agent_class = AGENTS.get(thread.agent)
    if agent_class is None:
        logger.error(
            "Unknown chat agent %r on thread %s", thread.agent, thread_id
        )
        _finish(thread, DemoChatThread.Status.FAILED, turn)
        return
    if _cancelled(thread_id):
        _finish(thread, DemoChatThread.Status.IDLE, turn)
        return
    _publish(
        thread_id, {"type": "status", "status": DemoChatThread.Status.RUNNING}
    )
    try:
        _run_steps(thread, agent_class(), turn)
    except _TurnLost:
        logger.warning(
            "Turn on thread %s was taken over mid-flight", thread_id
        )
        return
    except Exception:
        logger.exception("Chat turn failed on thread %s", thread_id)
        _finish(thread, DemoChatThread.Status.FAILED, turn)
        return
    _finish(thread, DemoChatThread.Status.IDLE, turn)


def demo_chat_turn_cancel(*, user: User, thread_id: str) -> None:
    """Flag the turn so the worker winds down; finish it when it is dead."""
    thread = DemoChatThread.objects.filter(id=thread_id, user=user).first()
    if thread is None:
        raise ApplicationError("Thread not found")
    busy = (DemoChatThread.Status.PENDING, DemoChatThread.Status.RUNNING)
    if thread.status not in busy:
        raise ApplicationError("No response is in progress")
    cache.set(
        demo_chat_cancel_cache_key(str(thread.id)),
        True,
        timeout=DEMO_CHAT_CANCEL_CACHE_TTL,
    )
    if thread.touched_at < _stale_cutoff():
        _finish(thread, DemoChatThread.Status.IDLE, thread.turn)


def demo_chat_thread_rename(
    *, user: User, thread_id: str, title: str
) -> DemoChatThread:
    """Rename a thread; a manual title outranks the generated one."""
    thread = DemoChatThread.objects.filter(id=thread_id, user=user).first()
    if thread is None:
        raise ApplicationError("Thread not found")
    cleaned = title.strip()[:100]
    if not cleaned:
        raise ApplicationError("Title must not be empty")
    thread.title = cleaned
    thread.full_clean()
    thread.save(update_fields=["title", "updated_at"])
    _publish(str(thread.id), {"type": "title", "title": cleaned})
    return thread


def demo_chat_thread_delete(*, user: User, thread_id: str) -> None:
    """Delete a thread, cancelling any turn still running on it."""
    thread = DemoChatThread.objects.filter(id=thread_id, user=user).first()
    if thread is None:
        raise ApplicationError("Thread not found")
    thread_id = str(thread.id)
    cache.set(
        demo_chat_cancel_cache_key(thread_id),
        True,
        timeout=DEMO_CHAT_CANCEL_CACHE_TTL,
    )
    thread.delete()
    _publish(thread_id, {"type": "deleted"})


def demo_chat_thread_state_update(
    *, thread_id: str, state: dict[str, Any]
) -> DemoChatThread | None:
    """Replace a thread's agent state, doing nothing if the thread is gone."""
    thread = DemoChatThread.objects.filter(id=thread_id).first()
    if thread is None:
        return None
    thread.state = state
    thread.full_clean()
    thread.save(update_fields=["state", "updated_at"])
    return thread


def demo_chat_thread_compact(
    *, thread: DemoChatThread
) -> DemoChatMessage | None:
    """Fold the answered history into a summary the projection reads instead.

    Trailing user messages are left out of the summary and stay live —
    they are what the next model call must answer — so the row records
    how far it covered rather than relying on its own position.
    """
    summary, live = _history(thread)
    boundary = len(live)
    while boundary and live[boundary - 1].data.get("role") == "user":
        boundary -= 1
    covered = live[:boundary]
    if not covered:
        return None
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": _with_summary(COMPACTION_PROMPT, summary),
        },
        *_llm_messages(covered),
        {"role": "user", "content": COMPACTION_INSTRUCTION},
    ]
    response = litellm.completion(model=COMPACTION_MODEL, messages=messages)
    new_summary = (response.choices[0].message.content or "").strip()
    input_tokens, output_tokens = _usage_tokens(response)
    row = demo_chat_message_create(
        thread=thread,
        kind=DemoChatMessage.Kind.COMPACTION,
        data={
            "role": "meta",
            "content": new_summary,
            "through": covered[-1].created_at.isoformat(),
        },
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=_cost(response, COMPACTION_MODEL),
    )
    _publish_message(thread, row, None)
    return row


def demo_chat_thread_title_generate(thread_id: str) -> None:
    """Title a thread from its first user message, once."""
    thread = DemoChatThread.objects.filter(id=thread_id).first()
    if thread is None or thread.title:
        return
    first = (
        thread.messages.filter(
            kind=DemoChatMessage.Kind.CHAT, data__role="user"
        )
        .order_by("created_at")
        .first()
    )
    if first is None:
        return
    content = str(first.data.get("content", ""))
    title = ""
    try:
        response = litellm.completion(
            model=TITLE_MODEL,
            messages=[
                {"role": "system", "content": TITLE_PROMPT},
                {"role": "user", "content": content[:TITLE_INPUT_MAX_CHARS]},
            ],
        )
        title = (response.choices[0].message.content or "").strip()[:100]
        input_tokens, output_tokens = _usage_tokens(response)
        demo_chat_message_create(
            thread=thread,
            kind=DemoChatMessage.Kind.META,
            data={"role": "meta", "content": "thread_title"},
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=_cost(response, TITLE_MODEL),
        )
    except Exception:
        logger.exception("Title generation failed on thread %s", thread_id)
    if not title:
        title = content[:TITLE_FALLBACK_MAX_CHARS]
    updated = DemoChatThread.objects.filter(id=thread.id, title="").update(
        title=title
    )
    if updated:
        _publish(str(thread.id), {"type": "title", "title": title})


def _run_steps(thread: DemoChatThread, agent: Agent, turn: UUID) -> None:
    """The tool loop: stream, execute, and repeat until the agent stops."""
    thread_id = str(thread.id)
    context = demo_chat_thread_context_tokens(thread=thread)
    if context > agent.compact_after_tokens:
        try:
            demo_chat_thread_compact(thread=thread)
        except Exception:
            logger.exception("Compaction failed on thread %s", thread_id)
    system_prompt = agent.get_system_prompt(thread)
    for _ in range(agent.max_steps):
        if _cancelled(thread_id):
            return
        row = _stream_completion(thread, agent, system_prompt, turn)
        calls = row.data.get("tool_calls") or []
        if row.data.get("interrupted") or not calls:
            return
        refresh = False
        for index, call in enumerate(calls):
            if _cancelled(thread_id):
                _cancel_remaining(thread, agent, row, calls[index:])
                return
            output = _execute_tool(agent, call, thread_id)
            function = call.get("function") or {}
            tool_row = demo_chat_message_create(
                thread=thread,
                data={
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "name": function.get("name", ""),
                    "content": output.result,
                    "render_data": output.render_data,
                },
                input_tokens=output.input_tokens,
                output_tokens=output.output_tokens,
                cost=output.cost,
            )
            _publish_message(thread, tool_row, agent)
            _touch(thread_id, turn)
            refresh = refresh or output.refresh_system_prompt
        thread.refresh_from_db(fields=["state"])
        _publish(
            thread_id,
            {"type": "state", **demo_chat_state_render(thread=thread)},
        )
        if refresh:
            system_prompt = agent.get_system_prompt(thread)


def _stream_completion(
    thread: DemoChatThread, agent: Agent, system_prompt: str, turn: UUID
) -> DemoChatMessage:
    """Stream one model call into a persisted assistant message."""
    thread_id = str(thread.id)
    messages = _messages_for_llm(thread, system_prompt=system_prompt)
    row = demo_chat_message_create(
        thread=thread, data={"role": "assistant", "content": ""}
    )
    _publish_message(thread, row, agent)
    call_args: dict[str, Any] = {
        "model": agent.model,
        "messages": messages,
        "max_tokens": agent.max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if agent.tool_schemas:
        call_args["tools"] = agent.tool_schemas
    content = ""
    offset = 0
    slots: dict[int, dict[str, Any]] = {}
    usage_chunk: Any = None
    interrupted = False
    flushed = 0
    last_flush = time.monotonic()
    for chunk in litellm.completion(**call_args):
        if getattr(chunk, "usage", None) is not None:
            usage_chunk = chunk
        text, deltas = _read_delta(chunk)
        if text:
            _publish(
                thread_id,
                {
                    "type": "content_delta",
                    "message_id": str(row.id),
                    "offset": offset,
                    "text": text,
                },
            )
            content += text
            offset += _utf16_length(text)
        _merge_tool_calls(slots, deltas)
        now = time.monotonic()
        if now - last_flush >= FLUSH_INTERVAL_SECONDS:
            last_flush = now
            DemoChatMessage.objects.filter(id=row.id).update(
                data={"role": "assistant", "content": content}
            )
            if len(content) != flushed:
                flushed = len(content)
                _publish(
                    thread_id,
                    {
                        "type": "content_set",
                        "message_id": str(row.id),
                        "text": content,
                    },
                )
            if not _touch(thread_id, turn):
                raise _TurnLost
            if _cancelled(thread_id):
                interrupted = True
                break
    data: dict[str, Any] = {"role": "assistant", "content": content}
    calls = [
        slots[index]
        for index in sorted(slots)
        if slots[index]["function"]["name"]
    ]
    if calls and not interrupted:
        data["tool_calls"] = calls
    if interrupted:
        data["interrupted"] = True
    input_tokens, output_tokens = _usage_tokens(usage_chunk)
    DemoChatMessage.objects.filter(id=row.id).update(
        data=data,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=_cost(usage_chunk, agent.model),
    )
    row.refresh_from_db()
    _publish_message(thread, row, agent)
    _publish(
        thread_id,
        {"type": "usage", "usage": demo_chat_thread_usage(thread=thread)},
    )
    return row


def _cancel_remaining(
    thread: DemoChatThread,
    agent: Agent,
    row: DemoChatMessage,
    calls: list[dict[str, Any]],
) -> None:
    """Close out unanswered tool calls so the history stays well-formed."""
    for call in calls:
        function = call.get("function") or {}
        cancelled = demo_chat_message_create(
            thread=thread,
            data={
                "role": "tool",
                "tool_call_id": call.get("id"),
                "name": function.get("name", ""),
                "content": "Cancelled by the user.",
                "cancelled": True,
            },
        )
        _publish_message(thread, cancelled, agent)
    row.data["interrupted"] = True
    DemoChatMessage.objects.filter(id=row.id).update(data=row.data)
    _publish_message(thread, row, agent)


def _execute_tool(
    agent: Agent, call: dict[str, Any], thread_id: str
) -> ToolOutput:
    """Run one tool call, turning any failure into an error result."""
    function = call.get("function") or {}
    name = str(function.get("name", ""))
    tool_class = agent.tools_by_name.get(name)
    if tool_class is None:
        return ToolOutput(result=f"Error: unknown tool {name}")
    try:
        arguments = json.loads(function.get("arguments") or "{}")
        tool = tool_class(**arguments)
        return tool(thread_id=thread_id)
    except Exception as exc:
        logger.exception("Tool %s failed on thread %s", name, thread_id)
        return ToolOutput(result=f"Error: {exc}")


def _messages_for_llm(
    thread: DemoChatThread, *, system_prompt: str
) -> list[dict[str, Any]]:
    """Project the thread into the message list a completion call takes."""
    summary, live = _history(thread)
    system = {
        "role": "system",
        "content": _with_summary(system_prompt, summary),
    }
    return [system, *_llm_messages(live)]


def _llm_messages(rows: list[DemoChatMessage]) -> list[dict[str, Any]]:
    """Project rows to API messages, closing out calls a dead turn left open."""
    messages: list[dict[str, Any]] = []
    pending: dict[str, str] = {}
    for row in rows:
        message = _to_llm_message(row.data)
        if message is None:
            continue
        if message["role"] == "tool":
            pending.pop(str(message.get("tool_call_id")), None)
        else:
            messages.extend(_interrupted_results(pending))
            pending = {
                str(call.get("id")): str(
                    (call.get("function") or {}).get("name", "")
                )
                for call in message.get("tool_calls") or []
            }
        messages.append(message)
    messages.extend(_interrupted_results(pending))
    return messages


def _interrupted_results(pending: dict[str, str]) -> list[dict[str, Any]]:
    """Synthetic tool results for calls whose turn died before answering."""
    return [
        {
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": "Interrupted before a result was recorded.",
        }
        for call_id, name in pending.items()
    ]


def _history(thread: DemoChatThread) -> tuple[str, list[DemoChatMessage]]:
    """The last compaction's summary and the chat rows still live after it."""
    rows = list(thread.messages.order_by("created_at"))
    compaction = None
    for row in rows:
        if row.kind == DemoChatMessage.Kind.COMPACTION:
            compaction = row
    summary = ""
    through = None
    if compaction is not None:
        summary = str(compaction.data.get("content", ""))
        raw = compaction.data.get("through")
        through = datetime.fromisoformat(raw) if raw else compaction.created_at
    live = [
        row
        for row in rows
        if row.kind == DemoChatMessage.Kind.CHAT
        and (through is None or row.created_at > through)
    ]
    return summary, live


def _with_summary(system_prompt: str, summary: str) -> str:
    """Append the compaction summary to a system prompt when one exists."""
    if not summary:
        return system_prompt
    return (
        f"{system_prompt}\n\n<conversation_summary>\n{summary}\n"
        "</conversation_summary>"
    )


def _to_llm_message(data: dict[str, Any]) -> dict[str, Any] | None:
    """Whitelist one stored message down to the keys the API accepts."""
    role = data.get("role")
    if role == "user":
        return {"role": "user", "content": data.get("content", "")}
    if role == "assistant":
        message: dict[str, Any] = {
            "role": "assistant",
            "content": data.get("content", ""),
        }
        if data.get("tool_calls"):
            message["tool_calls"] = data["tool_calls"]
        return message
    if role == "tool":
        return {
            "role": "tool",
            "tool_call_id": data.get("tool_call_id"),
            "name": data.get("name"),
            "content": data.get("content", ""),
        }
    return None


def _read_delta(chunk: Any) -> tuple[str, list[Any]]:
    """Pull the text and tool-call fragments out of one stream chunk."""
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return "", []
    delta = getattr(choices[0], "delta", None)
    if delta is None:
        return "", []
    return (
        getattr(delta, "content", None) or "",
        getattr(delta, "tool_calls", None) or [],
    )


def _merge_tool_calls(
    slots: dict[int, dict[str, Any]], deltas: list[Any]
) -> None:
    """Reassemble streamed tool-call fragments into complete calls."""
    for delta in deltas:
        index = getattr(delta, "index", 0) or 0
        slot = slots.setdefault(
            index,
            {
                "id": None,
                "type": "function",
                "function": {"name": "", "arguments": ""},
            },
        )
        if getattr(delta, "id", None):
            slot["id"] = delta.id
        function = getattr(delta, "function", None)
        if function is None:
            continue
        if getattr(function, "name", None):
            slot["function"]["name"] = function.name
        if getattr(function, "arguments", None):
            slot["function"]["arguments"] += function.arguments


def _usage_tokens(response: Any) -> tuple[int, int]:
    """Read prompt and completion token counts off a response, if present."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0
    return (
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
    )


def _cost(response: Any, model: str) -> float:
    """Price a completion response, absorbing pricing failures as zero."""
    if response is None:
        return 0.0
    try:
        return float(
            litellm.completion_cost(completion_response=response, model=model)
        )
    except Exception:
        logger.exception("completion_cost failed for %s", model)
        return 0.0


def _cancelled(thread_id: str) -> bool:
    """Whether a cancel request has flagged this thread's turn."""
    return bool(cache.get(demo_chat_cancel_cache_key(thread_id)))


def _stale_cutoff() -> datetime:
    """Busy statuses older than this belong to turns that died."""
    return timezone.now() - timedelta(seconds=TURN_STALE_SECONDS)


def _utf16_length(text: str) -> int:
    """The length a browser counts, which is UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def _touch(thread_id: str, turn: UUID) -> bool:
    """Freshen the liveness clock; False once another turn owns the thread."""
    return bool(
        DemoChatThread.objects.filter(id=thread_id, turn=turn).update(
            touched_at=timezone.now()
        )
    )


def _finish(thread: DemoChatThread, status: str, turn: UUID) -> None:
    """Record the turn's final status, unless another turn took over."""
    finished = DemoChatThread.objects.filter(id=thread.id, turn=turn).update(
        status=status
    )
    if not finished:
        return
    thread_id = str(thread.id)
    _publish(
        thread_id,
        {"type": "usage", "usage": demo_chat_thread_usage(thread=thread)},
    )
    _publish(thread_id, {"type": "status", "status": status})


@lru_cache(maxsize=1)
def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL)


def _publish(thread_id: str, event: dict[str, Any]) -> None:
    """Fan one turn event out; failures log, because the DB is authoritative."""
    try:
        _redis_client().publish(
            demo_chat_events_channel(thread_id), json.dumps(event)
        )
    except Exception:
        logger.exception("Event publish failed on thread %s", thread_id)


def _publish_message(
    thread: DemoChatThread, message: DemoChatMessage, agent: Agent | None
) -> None:
    """Ship one serialized message row to live viewers."""
    _publish(
        str(thread.id),
        {
            "type": "message",
            "message": demo_chat_message_serialize(
                message=message, agent=agent
            ),
        },
    )


def _queue_turn(thread: DemoChatThread) -> None:
    """Queue the turn task after the surrounding commit."""
    from clx.app.tasks import demo_chat_turn_run_task

    transaction.on_commit(
        lambda: demo_chat_turn_run_task.delay(str(thread.id))
    )


def _queue_title(thread: DemoChatThread) -> None:
    """Queue title generation after the surrounding commit."""
    from clx.app.tasks import demo_chat_thread_title_generate_task

    transaction.on_commit(
        lambda: demo_chat_thread_title_generate_task.delay(str(thread.id))
    )
