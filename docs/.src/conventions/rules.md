# The rule catalog

Each check module owns one family of rules and carries
[a `RULES` table](sym:c4029758bc1e,e31b0dce0c9d,ad5adef6a024,77046f7673c1,bda788276e3d,d0055842d58a,836323fdd9a7)
holding the CLAUDE.md text its messages quote. The families follow the id
ranges: E1xx imports, E2xx naming registers, E3xx URL surfaces, E4xx
template placement, E5xx Alpine, E6xx call discipline, E7xx auth coverage.

## Imports (E101–E105)

[`check_layer_imports`](sym:c5d829daffce+) enforces the layer matrix:
[`ALLOWED_IMPORTS`](sym:ffa35594dfe7) says which layers each layer may
import (models import only models; selectors add agents; interfaces —
api, views, tasks, management, mcp-tools — import models, selectors and
services but never each other), with
[`LAYER_PACKAGES`](sym:c7f382d4bff4) and [`_layer`](sym:0d7be8c9a90d+)
mapping modules to rows; anything outside the named packages (wiring like
`urls.py`) is unchecked. [`check_api_utils_boundary`](sym:6d3264b623d5+)
(E102) keeps API surfaces importing from the `api.utils` package root only,
so its `__init__` re-export list stays the real public interface.
[`check_mcp_direction`](sym:25aefc7713fb+) (E103) forbids `starter.app` from
importing `starter.mcp`, which is what keeps `starter/mcp/` deletable.
[`check_lazy_task_imports`](sym:d31ad87c9ae7+) (E104) requires services to
import the tasks layer inside function bodies — a module-level import would
tie the service to celery at import time and invite queueing outside
`on_commit`. [`check_app_modules_are_declared`](sym:74f6f4b46f1a+) (E105) is
the architecture ratchet: a top-level module of `starter/app` not in
[`DECLARED_APP_MODULES`](sym:4c76994653a3) is an error telling you to
declare it and write its ground rules into CLAUDE.md, so new architecture
cannot appear silently.

## Naming registers (E201–E205)

These run over [the direct domain modules of a layer
package](sym:5ebecacc7e31+), skipping underscore-prefixed stems and
[the `utils` machinery modules](sym:dab2907cad70).
[`check_domain_prefixes`](sym:269e8611a02f+) (E201): every public function
in `services/x.py` or `selectors/x.py` is named `x` or `x_...`, which is
what makes the codebase greppable by domain.
[`check_task_names`](sym:be1f1accb07b+) (E202) adds the `_task` suffix for
the tasks layer. [`check_model_reexports`](sym:57360eb1d3c6+) (E204)
compares the running app registry's concrete models against
`models/__init__.__all__`, so a model whose module was never re-exported
fails here rather than as a later `AttributeError` at an import site.
[`check_keyword_only_arguments`](sym:5f75457dec50+) (E205) counts positional
parameters from the AST and allows exactly one — the id-taking, task-style
entrypoints — with everything else behind `*`.
[`check_search_contract`](sym:380ecb918c2a+) (E203) requires every
`*_index` name builder in `search.py` to have its `*_MAPPING` and
`*_document` beside it, keeping the two halves of the index contract in one
file.

## URL surfaces (E301–E304)

All four run over the pattern-list facts, with
[`_surface`](sym:2e1a17c13bbe) deriving a list's surface name and expected
include prefix from its `_api_patterns` / `_view_patterns` suffix.
[`check_surface_triads`](sym:29bb6527425f+) (E301): list name, include
prefix and interface module agree — `users_api_patterns` is included at
`api/users/` and routes callbacks from `starter.app.api.users` only.
[`check_url_name_prefixes`](sym:111260157fd0+) (E302): URL names in a
prefixed list carry the surface prefix (`users-me`, `demos-jobs`).
[`check_url_name_uniqueness`](sym:e44b29ee403b+) (E303): a name on two
routes means `reverse()` silently resolves only one.
[`check_prefixes_live_at_the_include`](sym:cb42699f78fb+) (E304): a list
whose every route repeats its own surface should have the prefix applied
where the list is included instead.

## Template placement (E401–E407)

[`check_pages_are_routed`](sym:7650170c4c0a+) (E401) and
[`check_layouts_are_extended`](sym:0e33c2489da6+) (E402) kill dead markup:
every `pages/` template must be rendered by a route, every `layouts/`
template extended by something.
[`check_components_are_used`](sym:72582b4ab6fe+) (E403) does the same for
`cotton/`, with [`_tag`](sym:723f293ca169) computing the `<c-...>` tag a
path answers to — and a component counts as used when a Python string
literal names it, because declared rendering (an agent's
`tool_call_template`, a `render_to_string` call) is rendering.
[`check_no_includes`](sym:daa3a2b71369+) (E404) bans `{% include %}`
outright. [`check_no_same_name_pairs`](sym:9c08e54d3215+) (E405) forbids
`demos.html` beside `demos/`, and
[`check_surface_folders_have_an_index`](sym:8e7b21676474+) (E406) requires
each `pages/` folder to have an `index.html` or a redirecting bare route.
[`check_root_components_declare_cvars`](sym:ead4b25b250d+) (E407) holds
root-level cotton primitives to an explicit `<c-vars>` interface; nested
components inherit page context by design.

## Alpine (E501–E503)

[`check_directive_grammar`](sym:d12b7945b297+) parses every directive
expression in every template with the same parser the script collector
uses, flagging anything the CSP build cannot evaluate — operators,
arguments, assignments (E501), and `x-model` specifically (E502), whose
setter compiles to an assignment. The stakes are in the rule text: illegal
expressions fail silently to empty, so without the check nothing would
crash when one slipped in.
[`check_data_names_are_registered`](sym:a17ccc6333b7+) (E503) collects every
`Alpine.data` registration across all script blocks and flags an
`x-data="name"` no block registers — a component that would silently never
start.

## Call discipline (E601–E606)

These walk module ASTs — [everything except the
tests](sym:6c35022cd153+) — for call shapes.
[`check_cache_key_literals`](sym:ce9584a5fe91+) (E601) flags a literal or
f-string first argument to any of [the cache-API
methods](sym:a8b2eda5134a) on a name called `cache`; keys live in
`app/cache.py`. [`check_tasks_queue_on_commit`](sym:afb16571205e+) (E602)
finds `.delay()`/`.apply_async()` and [walks the parent chain looking for
an enclosing `on_commit` callable](sym:7bd5beac49f8,2306e74638ad) — a queue
call outside one races the transaction it belongs to.
[`check_signals_connect_in_ready`](sym:49be57e93491+) (E603) confines
`.connect()` calls and `@receiver` decorators to `apps.py` and
`signals.py`. [`check_writes_live_in_services`](sym:edcd3ee493d9+) (E604)
flags [model-write method calls](sym:181419899beb) and [queryset
writes](sym:e533d0877c66) in [the read layers](sym:24787bf7928c) —
selectors, agents, api, views, tasks, management, templatetags, mcp tools.
[`check_atomic_lives_in_services`](sym:d1b86888ec6f+) (E605) confines
`transaction.atomic` (as decorator or `with`) to services.
[`check_full_clean_before_save`](sym:440e2945d544+) (E606) matches receivers
by name within each service function: `row.save()` needs an earlier
`row.full_clean()`. Saves with positional arguments are skipped on purpose —
that shape is `storage.save(name, content)`, not a model save.

## Auth coverage (E701–E703)

[`check_api_routes_declare_auth`](sym:2d6613f4af0c+) (E701): every route
served from `api/` carries the `@api_auth` stash, so public is a recorded
decision rather than a forgotten decorator.
[`check_admin_views_require_permission`](sym:313bbeca10d2+) (E702): every
HTML view routed under `admin/` wears `@permission_required`.
[`check_mcp_tools_complete_their_annotations`](sym:4de932931b02+) (E703):
every MCP tool sets every `ToolAnnotations` field explicitly, even the ones
that only matter when `readOnlyHint` is false.
