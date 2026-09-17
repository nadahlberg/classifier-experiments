import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.test import Client
from elasticsearch import BadRequestError

from clx.app.models import (
    DemoAttorney,
    DemoDocket,
    DemoDocketEntry,
    DemoParty,
)
from clx.app.search import demo_docket_index, search_client
from clx.app.selectors.demo import (
    demo_docket_facet_options,
    demo_docket_search,
)
from clx.app.services.demo import (
    PACKAGED_DOCKETS,
    demo_docket_import,
    demo_docket_reindex,
)
from clx.app.services.user import user_create


def docket_record(**overrides: Any) -> dict[str, Any]:
    """A full docket record shaped like one line of the packaged sample."""
    record = {
        "docket_id": "usdc.mad_123",
        "court_id": "mad",
        "pacer_case_id": "12345",
        "case_name": "Doe v. Example Corp",
        "docket_number": "1:21-cv-1000",
        "date_filed": "2021-03-01",
        "date_terminated": "2022-01-15",
        "date_converted": None,
        "date_discharged": None,
        "assigned_to_str": "Jane Judge",
        "referred_to_str": "",
        "cause": "42:1983 Civil Rights Act",
        "nature_of_suit": "Civil Rights: Other",
        "jury_demand": "Plaintiff",
        "jurisdiction": "Federal Question",
        "demand": "$100,000",
        "mdl_status": "",
        "ordered_by": "date_filed",
        "federal_defendant_number": None,
        "federal_dn_case_type": "cv",
        "federal_dn_office_code": "1",
        "federal_dn_judge_initials_assigned": "JJ",
        "federal_dn_judge_initials_referred": None,
        "docket_entries": [
            {
                "date_filed": "2021-03-01",
                "date_entered": None,
                "document_number": "1",
                "pacer_doc_id": "09508267133",
                "pacer_seq_no": "18",
                "description": "COMPLAINT against Example Corp.",
            }
        ],
        "parties": [
            {
                "name": "Jane Doe",
                "type": "Plaintiff",
                "extra_info": "",
                "date_terminated": None,
                "attorneys": [
                    {
                        "name": "Ada Advocate",
                        "contact": "Firm LLP\n1 Main St",
                        "roles": ["LEAD ATTORNEY", "ATTORNEY TO BE NOTICED"],
                    }
                ],
            }
        ],
    }
    record.update(overrides)
    return record


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


@pytest.mark.django_db
def test_import_loads_every_level_and_tolerates_missing_keys(
    tmp_path: Path,
) -> None:
    """The sample data is ragged: pacer_case_id is absent from some dockets
    and the attorneys key from some parties, and most nullable fields arrive
    as explicit nulls. The importer has to treat a missing key and a null
    the same way — "" for text, None for dates — or the real file dies
    partway through with a KeyError after already deleting the old rows.
    """
    sparse = docket_record(
        docket_id="usdc.nyed_456",
        date_terminated=None,
        docket_entries=[],
        parties=[{"name": "Acme", "type": "Defendant"}],
    )
    del sparse["pacer_case_id"]
    source = write_jsonl(tmp_path / "dockets.jsonl", [docket_record(), sparse])

    counts = demo_docket_import(source)

    assert counts == {
        "dockets": 2,
        "entries": 1,
        "parties": 2,
        "attorneys": 1,
    }
    full = DemoDocket.objects.get(docket_id="usdc.mad_123")
    assert full.date_filed == datetime.date(2021, 3, 1)
    assert full.date_terminated == datetime.date(2022, 1, 15)
    assert full.federal_defendant_number == ""
    entry = full.entries.get()
    assert entry.description == "COMPLAINT against Example Corp."
    assert entry.date_entered is None
    attorney = full.parties.get().attorneys.get()
    assert attorney.roles == ["LEAD ATTORNEY", "ATTORNEY TO BE NOTICED"]
    sparse_row = DemoDocket.objects.get(docket_id="usdc.nyed_456")
    assert sparse_row.pacer_case_id == ""
    assert sparse_row.parties.get().attorneys.count() == 0


@pytest.mark.django_db
def test_import_replaces_the_tables_instead_of_appending(
    tmp_path: Path,
) -> None:
    """The page's button promises a from-scratch state: drop everything,
    reimport. Without the delete an import after a schema tweak would fail
    on the docket_id unique constraint at best, or silently double every
    table at worst. Rows that are not in the source anymore must also be
    gone, which an update-in-place importer would leave behind.
    """
    stale = write_jsonl(
        tmp_path / "stale.jsonl", [docket_record(docket_id="stale_1")]
    )
    fresh = write_jsonl(
        tmp_path / "fresh.jsonl",
        [docket_record(), docket_record(docket_id="usdc.nyed_456")],
    )
    demo_docket_import(stale)

    demo_docket_import(fresh)
    demo_docket_import(fresh)

    assert not DemoDocket.objects.filter(docket_id="stale_1").exists()
    assert DemoDocket.objects.count() == 2
    assert DemoDocketEntry.objects.count() == 2
    assert DemoParty.objects.count() == 2
    assert DemoAttorney.objects.count() == 2


def test_the_packaged_sample_is_where_the_importer_looks() -> None:
    """The import service reads the file that ships inside the application
    package, so the path is a contract between pyproject's package-data
    entry, the data directory, and PACKAGED_DOCKETS. This fails if the file
    moves or the name changes; the package-data line is what keeps the same
    path true after a pip install, where only declared files exist.
    """
    with PACKAGED_DOCKETS.open() as lines:
        record = json.loads(next(lines))

    assert "docket_id" in record
    assert "docket_entries" in record


@pytest.mark.django_db
def test_reindex_builds_a_searchable_alias(
    search_index: str, tmp_path: Path
) -> None:
    """The whole pipeline in one pass: rows in postgres, a rebuild, and a
    query answered through the alias — including a hit that only exists two
    relations deep, on an attorney nested under a party, which is what
    proves the document builder walks the full shape into the index.
    """
    source = write_jsonl(
        tmp_path / "dockets.jsonl",
        [
            docket_record(),
            docket_record(
                docket_id="usdc.nyed_456",
                case_name="Smith v. Neutrino Labs",
                parties=[],
                docket_entries=[],
            ),
        ],
    )
    demo_docket_import(source)

    count = demo_docket_reindex()

    assert count == 2
    by_attorney = demo_docket_search(query="Ada Advocate")
    assert [d.docket_id for d in by_attorney.dockets] == ["usdc.mad_123"]
    assert by_attorney.total == 1


@pytest.mark.django_db
def test_search_hydrates_postgres_rows_in_rank_order(
    search_index: str, tmp_path: Path
) -> None:
    """The selector returns model instances, not documents: elasticsearch
    supplies ids and ranking, postgres supplies the rows. A plain
    filter(docket_id__in=...) would hand back database order and silently
    throw the ranking away, so the reordering step is the part this pins —
    a case-name match (boosted) must beat a match buried in an entry.
    """
    source = write_jsonl(
        tmp_path / "dockets.jsonl",
        [
            docket_record(
                docket_id="weak",
                case_name="Doe v. Example Corp",
                docket_entries=[
                    {
                        "date_filed": "2021-03-01",
                        "date_entered": None,
                        "document_number": "1",
                        "pacer_doc_id": None,
                        "pacer_seq_no": None,
                        "description": "Motion mentioning Neutrino once.",
                    }
                ],
            ),
            docket_record(
                docket_id="strong",
                case_name="Smith v. Neutrino Labs",
            ),
        ],
    )
    demo_docket_import(source)
    demo_docket_reindex()

    results = demo_docket_search(query="Neutrino")

    assert [d.docket_id for d in results.dockets] == ["strong", "weak"]
    assert all(isinstance(d, DemoDocket) for d in results.dockets)
    assert (
        results.dockets[0].pk == DemoDocket.objects.get(docket_id="strong").pk
    )


@pytest.mark.django_db
def test_reindex_swaps_the_alias_and_drops_the_old_index(
    search_index: str, tmp_path: Path
) -> None:
    """A rebuild writes a fresh physical index and moves the alias in one
    atomic update, so searches never see a half-built index and a mapping
    change deploys by rebuilding. The same update deletes the replaced
    index — without that, every rebuild would leak a full copy of the
    data, and the wildcard cleanup would quietly stop fitting on the node.
    """
    source = write_jsonl(tmp_path / "dockets.jsonl", [docket_record()])
    demo_docket_import(source)

    demo_docket_reindex()
    demo_docket_reindex()

    physical = list(
        search_client().indices.get(index=f"{demo_docket_index()}-*")
    )
    assert len(physical) == 1
    assert demo_docket_search(query="Example").total == 1


@pytest.mark.django_db
def test_the_mapping_rejects_fields_it_does_not_name(
    search_index: str,
) -> None:
    """The mapping sets dynamic strict, the same fail-loudly stance as
    ToolInputs' extra=forbid: a field the mapping does not declare is a
    drifted document builder, and dynamic mapping would otherwise guess a
    type for it silently and freeze that guess into the index.
    """
    demo_docket_reindex()

    with pytest.raises(BadRequestError):
        search_client().index(
            index=demo_docket_index(),
            id="drifted",
            document={"docket_id": "drifted", "not_in_the_mapping": True},
        )


@pytest.mark.django_db
def test_facets_are_disjunctive_and_filters_narrow_the_hits(
    search_index: str, tmp_path: Path
) -> None:
    """Facet filters apply as a post_filter, and each facet's aggregation
    carries every filter except its own. That split is what keeps every
    option visible and one click away while a value is selected — a facet
    filtered by itself would collapse to the selected value and force a
    deselect-then-reselect round trip. The other facet's counts do narrow,
    because for them the selection is genuinely a filter, and the hit
    total narrows because post_filter applies to the hits.
    """
    source = write_jsonl(
        tmp_path / "dockets.jsonl",
        [
            docket_record(jury_demand="Both"),
            docket_record(docket_id="usdc.nyed_456", jurisdiction="Diversity"),
            docket_record(docket_id="usdc.cand_789", jurisdiction="Diversity"),
        ],
    )
    demo_docket_import(source)
    demo_docket_reindex()

    unfiltered = demo_docket_search()
    filtered = demo_docket_search(jurisdiction="Diversity")

    assert unfiltered.total == 3
    assert {
        bucket["value"]: bucket["count"]
        for bucket in unfiltered.facets["jurisdiction"]
    } == {"Diversity": 2, "Federal Question": 1}
    assert filtered.total == 2
    assert {d.docket_id for d in filtered.dockets} == {
        "usdc.nyed_456",
        "usdc.cand_789",
    }
    assert {
        bucket["value"]: bucket["count"]
        for bucket in filtered.facets["jurisdiction"]
    } == {"Diversity": 2, "Federal Question": 1}
    assert {
        bucket["value"]: bucket["count"]
        for bucket in filtered.facets["jury_demand"]
    } == {"Plaintiff": 2}


@pytest.mark.django_db
def test_facet_options_are_the_corpus_schema_not_the_result_set(
    search_index: str, tmp_path: Path
) -> None:
    """The sidebar's option lists come from their own selector over the
    whole corpus, in a request of their own: the sidebar can render before
    the first search answers, and a query with zero hits zeroes the counts
    without collapsing the lists — the collapse was exactly the bug when
    options were read off the search response's aggregations.
    """
    source = write_jsonl(
        tmp_path / "dockets.jsonl",
        [
            docket_record(jury_demand="Both"),
            docket_record(docket_id="usdc.nyed_456", jurisdiction="Diversity"),
            docket_record(docket_id="usdc.cand_789", jurisdiction="Diversity"),
        ],
    )
    demo_docket_import(source)
    demo_docket_reindex()

    options = demo_docket_facet_options()
    nothing = demo_docket_search(query="zz_matches_nothing_zz")

    assert {
        option["value"]: option["count"] for option in options["jurisdiction"]
    } == {"Diversity": 2, "Federal Question": 1}
    assert {
        option["value"]: option["count"] for option in options["jury_demand"]
    } == {"Plaintiff": 2, "Both": 1}
    assert nothing.total == 0


@pytest.mark.django_db
def test_facet_options_endpoint_requires_a_session(
    search_index: str, tmp_path: Path, client: Client
) -> None:
    """Same auth gate as the search endpoint, same shape as the selector —
    the page fetches this once at start, in parallel with the first
    search.
    """
    demo_docket_import(
        write_jsonl(tmp_path / "dockets.jsonl", [docket_record()])
    )
    demo_docket_reindex()

    assert (
        client.get("/api/demos/dockets/facets/", secure=True).status_code
        == 401
    )
    client.force_login(user_create(email="facets@example.com"))

    response = client.get("/api/demos/dockets/facets/", secure=True)

    assert response.status_code == 200
    assert response.json()["facets"]["jurisdiction"] == [
        {"value": "Federal Question", "count": 1}
    ]


@pytest.mark.django_db
def test_cursor_pages_walk_the_whole_set_without_gaps_or_repeats(
    search_index: str, tmp_path: Path
) -> None:
    """search_after pages by the last hit's sort values instead of an
    offset, so the walk must partition the result set exactly: every
    docket appears once, the short last page closes with no next cursor.
    The date sort alone cannot guarantee that — dockets share dates — so
    this also pins the docket_id tiebreaker that makes the ordering total.
    """
    records = [
        docket_record(
            docket_id=f"walk_{index}",
            date_filed=f"2021-03-0{index % 3 + 1}",
        )
        for index in range(5)
    ]
    demo_docket_import(write_jsonl(tmp_path / "dockets.jsonl", records))
    demo_docket_reindex()

    seen: list[str] = []
    after = None
    pages = 0
    while True:
        results = demo_docket_search(sort="newest", after=after, limit=2)
        seen.extend(d.docket_id for d in results.dockets)
        pages += 1
        if results.next_after is None:
            break
        after = results.next_after

    assert pages == 3
    assert len(results.dockets) == 1
    assert sorted(seen) == sorted(r["docket_id"] for r in records)


@pytest.mark.django_db
def test_search_endpoint_pages_serializes_and_binds_the_cursor(
    search_index: str, tmp_path: Path, client: Client
) -> None:
    """The endpoint's whole surface in one pass: issue #57's response
    shape (results, next, and the standard error shape for a bad cursor),
    the serialized card fields the page renders — including the windowed
    three-entry preview and the party overflow label — and the cursor
    being bound to its sort, so replaying a newest cursor under oldest is
    a 400 instead of an elasticsearch error bubbling as a 500.
    """
    many_entries = [
        {
            "date_filed": f"2021-03-0{index + 1}",
            "date_entered": None,
            "document_number": str(index + 1),
            "pacer_doc_id": None,
            "pacer_seq_no": None,
            "description": f"Filing number {index + 1}",
        }
        for index in range(5)
    ]
    many_parties = [
        {"name": f"Party {index}", "type": "Defendant"} for index in range(6)
    ]
    source = write_jsonl(
        tmp_path / "dockets.jsonl",
        [
            docket_record(
                date_filed="2020-01-01",
                docket_entries=many_entries,
                parties=many_parties,
            ),
            docket_record(docket_id="usdc.nyed_456"),
            docket_record(docket_id="usdc.cand_789"),
        ],
    )
    demo_docket_import(source)
    demo_docket_reindex()

    assert client.get("/api/demos/dockets/", secure=True).status_code == 401
    client.force_login(user_create(email="searcher@example.com"))

    first = client.get(
        "/api/demos/dockets/?sort=oldest&limit=2", secure=True
    ).json()
    assert first["total"] == 3
    assert first["page_size"] == 2
    assert len(first["results"]) == 2
    hit = first["results"][0]
    assert hit["case_name"] == "Doe v. Example Corp"
    assert len(hit["entries"]) == 3
    assert hit["entries"][0]["description"] == "Filing number 1"
    assert hit["more_entries_label"] == "2 more entries"
    assert hit["parties_label"].endswith("+2 more")
    assert first["next"]

    second = client.get(
        f"/api/demos/dockets/?sort=oldest&limit=2&cursor={first['next']}",
        secure=True,
    ).json()
    assert len(second["results"]) == 1
    assert second["next"] == ""

    mismatched = client.get(
        f"/api/demos/dockets/?sort=newest&limit=2&cursor={first['next']}",
        secure=True,
    )
    assert mismatched.status_code == 400
    assert "sort" in mismatched.json()["message"]

    garbage = client.get(
        "/api/demos/dockets/?cursor=@@not-a-cursor@@", secure=True
    )
    assert garbage.status_code == 400
    assert garbage.json()["message"] == "Invalid cursor"


@pytest.mark.django_db
def test_import_queues_a_reindex_only_after_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    """The sync contract: whatever lands in postgres is what elastic
    serves, so the import queues a rebuild — and queues it on_commit, so a
    rolled-back import can never trigger a task that would index rows the
    database no longer holds.
    """
    calls: list[bool] = []
    monkeypatch.setattr(
        "clx.app.tasks.demo_docket_reindex_task",
        SimpleNamespace(delay=lambda: calls.append(True)),
    )
    source = write_jsonl(tmp_path / "dockets.jsonl", [docket_record()])

    with django_capture_on_commit_callbacks(execute=True):
        demo_docket_import(source)
        assert calls == []

    assert calls == [True]


@pytest.mark.django_db
def test_import_endpoint_requires_a_session_and_returns_counts(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anonymous callers must not be able to drop and rebuild the tables.
    The endpoint is stubbed here because the real service reads the 36MB
    packaged file — its behaviour is covered above; what this pins is the
    auth gate and that the counts pass through as the response body.
    """
    counts = {"dockets": 1, "entries": 2, "parties": 3, "attorneys": 4}
    monkeypatch.setattr("clx.app.api.demos.demo_docket_import", lambda: counts)

    anonymous = client.post("/api/demos/dockets/import/", secure=True)
    assert anonymous.status_code == 401

    client.force_login(user_create(email="importer@example.com"))
    response = client.post("/api/demos/dockets/import/", secure=True)

    assert response.status_code == 200
    assert response.json() == counts
