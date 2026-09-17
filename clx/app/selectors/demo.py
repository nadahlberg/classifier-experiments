from dataclasses import dataclass
from typing import Any, cast

from django.core.cache import cache
from django.db.models import Count, F, Prefetch, Window
from django.db.models.functions import RowNumber

from clx.app.cache import DEMO_HEARTBEAT_CACHE_KEY
from clx.app.models import (
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
