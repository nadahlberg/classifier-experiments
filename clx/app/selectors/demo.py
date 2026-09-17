import json
from dataclasses import dataclass
from typing import Any, cast

from django.core.cache import cache
from django.db.models import Count, F, Prefetch, Sum, Window
from django.db.models.functions import RowNumber
from django.template.loader import render_to_string

from clx.app.agents import (
    AGENTS,
    Agent,
    render_tool_call,
    render_tool_result,
)
from clx.app.cache import DEMO_HEARTBEAT_CACHE_KEY
from clx.app.models import (
    DemoChatMessage,
    DemoChatThread,
    DemoDocket,
    DemoDocketEntry,
    DemoJob,
    DemoParty,
    DemoUpload,
    User,
)
from clx.app.search import demo_docket_index, search_client

DEMO_DOCKET_SEARCH_FIELDS = [
    "case_name^3",
    "docket_number^3",
    "parties.name^2",
    "parties.attorneys.name^2",
    "cause",
    "assigned_to_str",
    "referred_to_str",
    "parties.extra_info",
    "parties.attorneys.contact",
    "entries.description",
]

DEMO_DOCKET_SORTS: dict[str, list[dict[str, str]]] = {
    "relevance": [{"_score": "desc"}, {"docket_id": "asc"}],
    "newest": [{"date_filed": "desc"}, {"docket_id": "asc"}],
    "oldest": [{"date_filed": "asc"}, {"docket_id": "asc"}],
}

DEMO_DOCKET_FACETS = ("jurisdiction", "jury_demand")
DEMO_DOCKET_SEARCH_LIMIT = 30
DEMO_DOCKET_SEARCH_MAX_LIMIT = 100
DEMO_DOCKET_PREVIEW_ENTRIES = 3


@dataclass
class DemoDocketSearchResults:
    total: int
    dockets: list[DemoDocket]
    facets: dict[str, list[dict[str, Any]]]
    next_after: list[Any] | None
    limit: int


def demo_docket_search(
    *,
    query: str = "",
    jurisdiction: str = "",
    jury_demand: str = "",
    sort: str = "relevance",
    after: list[Any] | None = None,
    limit: int = DEMO_DOCKET_SEARCH_LIMIT,
) -> DemoDocketSearchResults:
    """Search the dockets index, hydrating hits from postgres in rank order."""
    limit = max(1, min(limit, DEMO_DOCKET_SEARCH_MAX_LIMIT))
    must: dict[str, Any] = (
        {
            "multi_match": {
                "query": query,
                "fields": DEMO_DOCKET_SEARCH_FIELDS,
            }
        }
        if query.strip()
        else {"match_all": {}}
    )
    selected = {
        name: {"term": {name: value}}
        for name, value in (
            ("jurisdiction", jurisdiction),
            ("jury_demand", jury_demand),
        )
        if value
    }
    response = search_client().search(
        index=demo_docket_index(),
        query={"bool": {"must": [must]}},
        post_filter=(
            {"bool": {"filter": list(selected.values())}} if selected else None
        ),
        sort=DEMO_DOCKET_SORTS[sort],
        size=limit + 1,
        search_after=after,
        source=False,
        track_total_hits=True,
        aggs={
            name: {
                "filter": {
                    "bool": {
                        "filter": [
                            term
                            for other, term in selected.items()
                            if other != name
                        ]
                    }
                },
                "aggs": {"values": {"terms": {"field": name, "size": 20}}},
            }
            for name in DEMO_DOCKET_FACETS
        },
    )
    hits = response["hits"]["hits"]
    page = hits[:limit]
    ids: list[str] = [hit["_id"] for hit in page]
    rows = _demo_docket_hydrate(ids)
    return DemoDocketSearchResults(
        total=int(response["hits"]["total"]["value"]),
        dockets=[rows[docket_id] for docket_id in ids if docket_id in rows],
        facets={
            name: [
                {"value": bucket["key"], "count": bucket["doc_count"]}
                for bucket in response["aggregations"][name]["values"][
                    "buckets"
                ]
            ]
            for name in DEMO_DOCKET_FACETS
        },
        next_after=list(page[-1]["sort"]) if len(hits) > limit else None,
        limit=limit,
    )


def demo_docket_facet_options() -> dict[str, list[dict[str, Any]]]:
    """Every facet value in the corpus, with corpus-wide counts."""
    response = search_client().search(
        index=demo_docket_index(),
        size=0,
        aggs={
            name: {"terms": {"field": name, "size": 20}}
            for name in DEMO_DOCKET_FACETS
        },
    )
    return {
        name: [
            {"value": bucket["key"], "count": bucket["doc_count"]}
            for bucket in response["aggregations"][name]["buckets"]
        ]
        for name in DEMO_DOCKET_FACETS
    }


def _demo_docket_hydrate(ids: list[str]) -> dict[str, DemoDocket]:
    """Fetch hit rows with parties, entry counts, and the first few entries."""
    first_entries = (
        DemoDocketEntry.objects.annotate(
            row=Window(
                RowNumber(),
                partition_by=F("docket_id"),
                order_by=[F("date_filed").asc(), F("id").asc()],
            )
        )
        .filter(row__lte=DEMO_DOCKET_PREVIEW_ENTRIES)
        .order_by("date_filed", "id")
    )
    rows = (
        DemoDocket.objects.filter(docket_id__in=ids)
        .annotate(entry_count=Count("entries"))
        .prefetch_related(
            Prefetch(
                "parties",
                queryset=DemoParty.objects.order_by("created_at"),
            ),
            Prefetch(
                "entries",
                queryset=first_entries,
                to_attr="first_entries",
            ),
        )
        .in_bulk(ids, field_name="docket_id")
    )
    return cast("dict[str, DemoDocket]", rows)


def demo_upload_list(*, user: User, limit: int = 100) -> list[DemoUpload]:
    """The user's uploads, newest first."""
    return list(
        DemoUpload.objects.filter(user=user).order_by("-created_at")[:limit]
    )


def demo_upload_get(*, user: User, upload_id: str) -> DemoUpload | None:
    """One of the user's uploads, or None."""
    return DemoUpload.objects.filter(id=upload_id, user=user).first()


def demo_heartbeat_read() -> str | None:
    """The ISO timestamp of the last heartbeat run, straight from the cache."""
    value = cache.get(DEMO_HEARTBEAT_CACHE_KEY)
    return value if isinstance(value, str) else None


def demo_job_list(*, user: User, limit: int = 20) -> list[DemoJob]:
    """The user's top-level demo jobs, newest first, with children attached."""
    return list(
        DemoJob.objects.filter(user=user, parent=None)
        .prefetch_related(
            Prefetch(
                "children",
                queryset=DemoJob.objects.order_by("created_at"),
            )
        )
        .order_by("-created_at")[:limit]
    )


def demo_chat_thread_list(
    *, user: User, limit: int = 50
) -> list[DemoChatThread]:
    """The user's chat threads, most recently active first."""
    return list(
        DemoChatThread.objects.filter(user=user).order_by("-updated_at")[
            :limit
        ]
    )


def demo_chat_thread_get(
    *, user: User, thread_id: str
) -> DemoChatThread | None:
    """One of the user's chat threads, or None."""
    return DemoChatThread.objects.filter(id=thread_id, user=user).first()


def demo_chat_thread_context_tokens(*, thread: DemoChatThread) -> int:
    """The input size of the newest model call since the last compaction."""
    rows = thread.messages.filter(
        kind=DemoChatMessage.Kind.CHAT, data__role="assistant"
    )
    compaction = (
        thread.messages.filter(kind=DemoChatMessage.Kind.COMPACTION)
        .order_by("-created_at")
        .first()
    )
    if compaction is not None:
        rows = rows.filter(created_at__gt=compaction.created_at)
    latest = rows.order_by("-created_at").first()
    return latest.input_tokens if latest else 0


def demo_chat_thread_usage(*, thread: DemoChatThread) -> dict[str, Any]:
    """The numbers behind the thread's cost line and token bar."""
    totals = thread.messages.aggregate(total_cost=Sum("cost"))
    agent_class = AGENTS.get(thread.agent)
    return {
        "context_tokens": demo_chat_thread_context_tokens(thread=thread),
        "compact_after_tokens": (
            agent_class.compact_after_tokens if agent_class else 0
        ),
        "total_cost": totals["total_cost"] or 0.0,
    }


def demo_chat_state_render(*, thread: DemoChatThread) -> dict[str, Any]:
    """The thread's agent state plus its rendered panel, when declared."""
    agent_class = AGENTS.get(thread.agent)
    template = agent_class.state_template if agent_class else None
    return {
        "state": thread.state,
        "state_html": (
            render_to_string(template, {"state": thread.state})
            if template
            else None
        ),
    }


def demo_chat_message_serialize(
    *, message: DemoChatMessage, agent: Agent | None
) -> dict[str, Any]:
    """One message row as the payload events and snapshots ship."""
    data = message.data
    role = str(data.get("role", ""))
    payload: dict[str, Any] = {
        "id": str(message.id),
        "kind": message.kind,
        "role": role,
        "created_at": message.created_at.isoformat(),
    }
    if message.kind == DemoChatMessage.Kind.COMPACTION:
        payload["content"] = str(data.get("content", ""))
        return payload
    if role == "tool":
        name = str(data.get("name", ""))
        tool = agent.tools_by_name.get(name) if agent else None
        render_data = data.get("render_data")
        render = (
            {"render_mode": "skip"}
            if data.get("cancelled")
            else render_tool_result(tool, render_data)
        )
        payload.update(
            {
                "tool_call_id": data.get("tool_call_id"),
                "name": name,
                "content": str(data.get("content", "")),
                "render_data": render_data,
                **render,
            }
        )
        return payload
    payload["content"] = str(data.get("content", ""))
    if role == "assistant":
        payload["interrupted"] = bool(data.get("interrupted"))
        payload["tool_calls"] = [
            _serialize_call(call, agent)
            for call in data.get("tool_calls") or []
        ]
    return payload


def demo_chat_thread_snapshot(*, thread: DemoChatThread) -> dict[str, Any]:
    """Everything the page needs to render a thread."""
    agent_class = AGENTS.get(thread.agent)
    agent = agent_class() if agent_class else None
    rows = thread.messages.exclude(kind=DemoChatMessage.Kind.META).order_by(
        "created_at"
    )
    return {
        "thread": {
            "id": str(thread.id),
            "title": thread.title,
            "status": thread.status,
            "agent": thread.agent,
        },
        **demo_chat_state_render(thread=thread),
        "usage": demo_chat_thread_usage(thread=thread),
        "messages": [
            demo_chat_message_serialize(message=row, agent=agent)
            for row in rows
        ],
    }


def _serialize_call(
    call: dict[str, Any], agent: Agent | None
) -> dict[str, Any]:
    function = call.get("function") or {}
    name = str(function.get("name", ""))
    args = _parse_arguments(function.get("arguments"))
    tool = agent.tools_by_name.get(name) if agent else None
    return {
        "id": call.get("id"),
        "name": name,
        "args": args,
        **render_tool_call(tool, args),
    }


def _parse_arguments(arguments: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
