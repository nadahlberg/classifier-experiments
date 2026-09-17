# Uninstall Elasticsearch

Removes search end to end: the index contract, the docket demo that
exercises it, its four models, the 36 MB sample data, and the cluster
from compose, CI, and infra. Nothing outside the docket demo consumes
search, so the product surface is unchanged. Keep
`clx/app/api/utils/pagination.py` and its tests — cursor paging
is generic machinery that outlives its one demo consumer. **This
removes models: run the migration reset afterwards.**

## Remove whole files

1. `clx/app/search.py`.
2. `clx/app/tests/test_demo_docket.py`.
3. `clx/data/dockets.jsonl`; the
   `[tool.setuptools.package-data]` entry in `pyproject.toml`; the
   `exclude: ^clx/data/` line in `.pre-commit-config.yaml`.
4. `clx/app/templates/pages/demos/search.html`, the whole
   `clx/app/templates/cotton/demos/search/` directory, and
   `clx/app/templates/cotton/demos/import_data.html`.

## Shared-file edits

5. `clx/app/models/demo.py`: delete `DemoDocket`,
   `DemoDocketEntry`, `DemoParty`, and `DemoAttorney` (and their
   re-exports in `clx/app/models/__init__.py`).
6. `clx/app/selectors/demo.py`: delete the docket block —
   `DEMO_DOCKET_SEARCH_FIELDS`, `DEMO_DOCKET_SORTS`,
   `DEMO_DOCKET_FACETS`, `DEMO_DOCKET_SEARCH_LIMIT`,
   `DEMO_DOCKET_SEARCH_MAX_LIMIT`, `DEMO_DOCKET_PREVIEW_ENTRIES`,
   `DemoDocketSearchResults`, `demo_docket_search`,
   `demo_docket_facet_options`, `_demo_docket_hydrate` — plus the
   `clx.app.search` import and the docket models in the models
   import.
7. `clx/app/services/demo.py`: delete `PACKAGED_DOCKETS`,
   `demo_docket_import`, `_queue_reindex`, `demo_docket_reindex`,
   `_text`, `_date`, and the search/elasticsearch imports.
8. `clx/app/tasks/demo.py`: delete `demo_docket_reindex_task`
   and its re-export in `clx/app/tasks/__init__.py`.
9. `clx/app/api/demos.py`: delete `docket_import`,
   `docket_facet_options`, `docket_search`, `_docket_hit`, and
   `DOCKET_PREVIEW_PARTIES`; in `clx/app/urls.py`, the three
   `dockets/` entries in `demos_api_patterns` and the
   `path("search/", ...)` entry in `demos_view_patterns`.
10. The `search` view in `clx/app/views/demos.py` and the
    Elasticsearch tile in
    `clx/app/templates/pages/demos/index.html`.
11. `clx/settings.py`: delete `ELASTICSEARCH_URL` and
    `ELASTICSEARCH_INDEX_PREFIX`.
12. `clx/app/services/health.py`: delete `check_elasticsearch`
    and the `"elasticsearch"` entries in `ServiceName` and `CHECKS`.

## Compose, CI, infra

13. `docker-compose.yml`: the `elasticsearch` service and its
    volume, the `elasticsearch` entry in the django service's
    `depends_on`, the `ELASTICSEARCH_URL` env on the django and
    celery services, and `elasticsearch` in the django healthcheck's
    `services=` list.
14. `.github/workflows/ci.yml`: the `elasticsearch` service
    container in the `test` job.
15. `infra/__main__.py`: the elasticsearch StatefulSet and Service,
    `ELASTICSEARCH_URL` in the app env secret, and `elasticsearch`
    in the readiness probe's `services=` list.
16. `pyproject.toml`: the `elasticsearch` dependency.

## Checks and explorer

17. `clx/app/selectors/codebase.py`: the module-level
    `from clx.app import search as search_registry` import
    **must** go or `manage check` and the admin explorer crash the
    moment `search.py` is deleted — remove it along with
    `build_search_indexes` and its call in `build()`.
18. `clx/app/checks/__init__.py`: the
    `facts.modules["clx.app.search"]` lookup and the
    `check_search_contract` wiring — both raise once the module is
    gone; `clx/app/checks/registers.py`: `check_search_contract`
    (E203) and its RULES entry; the E203 case in
    `clx/app/tests/test_checks.py`.
19. `clx/app/checks/imports.py`: `"search"` in
    `DECLARED_APP_MODULES`; `cotton/admin/codebase/explorer.html`:
    the `search-index` row of `CODEBASE_LAYERS`; the search-index
    tests in `clx/app/tests/test_codebase.py`.

## Tests

20. `clx/app/tests/conftest.py`: delete the `search_index`
    fixture and the `search_client` import.
21. `clx/app/tests/test_health.py`: delete the
    elasticsearch-specific tests; the `set(CHECKS)` assertion adjusts
    itself.

Delete the "## Search" section of CLAUDE.md, then run the migration
reset and the verify suite.
