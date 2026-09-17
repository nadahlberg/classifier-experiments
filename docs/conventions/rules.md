# The rule catalog

Each check module owns one family of rules and carries
[a `RULES` table](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/imports.py#L56-L79)
holding the CLAUDE.md text its messages quote. The families follow the id
ranges: E1xx imports, E2xx naming registers, E3xx URL surfaces, E4xx
template placement, E5xx Alpine, E6xx call discipline, E7xx auth coverage.

## Imports (E101–E105)

[`check_layer_imports`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/imports.py#L90-L118) enforces the layer matrix:
[`ALLOWED_IMPORTS`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/imports.py#L44-L54) says which layers each layer may
import (models import only models; selectors add agents; interfaces —
api, views, tasks, management, mcp-tools — import models, selectors and
services but never each other), with
[`LAYER_PACKAGES`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/imports.py#L32-L42) and [`_layer`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/imports.py#L82-L87)
mapping modules to rows; anything outside the named packages (wiring like
`urls.py`) is unchecked. [`check_api_utils_boundary`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/imports.py#L121-L149)
(E102) keeps API surfaces importing from the `api.utils` package root only,
so its `__init__` re-export list stays the real public interface.
[`check_mcp_direction`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/imports.py#L152-L178) (E103) forbids `starter.app` from
importing `starter.mcp`, which is what keeps `starter/mcp/` deletable.
[`check_lazy_task_imports`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/imports.py#L209-L237) (E104) requires services to
import the tasks layer inside function bodies — a module-level import would
tie the service to celery at import time and invite queueing outside
`on_commit`. [`check_app_modules_are_declared`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/imports.py#L181-L206) (E105) is
the architecture ratchet: a top-level module of `starter/app` not in
[`DECLARED_APP_MODULES`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/imports.py#L8-L30) is an error telling you to
declare it and write its ground rules into CLAUDE.md, so new architecture
cannot appear silently.

## Naming registers (E201–E205)

These run over [the direct domain modules of a layer
package](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/registers.py#L38-L50), skipping underscore-prefixed stems and
[the `utils` machinery modules](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/registers.py#L9).
[`check_domain_prefixes`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/registers.py#L53-L77) (E201): every public function
in `services/x.py` or `selectors/x.py` is named `x` or `x_...`, which is
what makes the codebase greppable by domain.
[`check_task_names`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/registers.py#L80-L103) (E202) adds the `_task` suffix for
the tasks layer. [`check_model_reexports`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/registers.py#L106-L126) (E204)
compares the running app registry's concrete models against
`models/__init__.__all__`, so a model whose module was never re-exported
fails here rather than as a later `AttributeError` at an import site.
[`check_keyword_only_arguments`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/registers.py#L129-L154) (E205) counts positional
parameters from the AST and allows exactly one — the id-taking, task-style
entrypoints — with everything else behind `*`.
[`check_search_contract`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/registers.py#L157-L194) (E203) requires every
`*_index` name builder in `search.py` to have its `*_MAPPING` and
`*_document` beside it, keeping the two halves of the index contract in one
file.

## URL surfaces (E301–E304)

All four run over the pattern-list facts, with
[`_surface`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/surfaces.py#L27-L33) deriving a list's surface name and expected
include prefix from its `_api_patterns` / `_view_patterns` suffix.
[`check_surface_triads`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/surfaces.py#L36-L78) (E301): list name, include
prefix and interface module agree — `users_api_patterns` is included at
`api/users/` and routes callbacks from `starter.app.api.users` only.
[`check_url_name_prefixes`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/surfaces.py#L81-L106) (E302): URL names in a
prefixed list carry the surface prefix (`users-me`, `demos-jobs`).
[`check_url_name_uniqueness`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/surfaces.py#L109-L132) (E303): a name on two
routes means `reverse()` silently resolves only one.
[`check_prefixes_live_at_the_include`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/surfaces.py#L135-L158) (E304): a list
whose every route repeats its own surface should have the prefix applied
where the list is included instead.

## Template placement (E401–E407)

[`check_pages_are_routed`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/templates.py#L45-L70) (E401) and
[`check_layouts_are_extended`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/templates.py#L73-L96) (E402) kill dead markup:
every `pages/` template must be rendered by a route, every `layouts/`
template extended by something.
[`check_components_are_used`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/templates.py#L99-L124) (E403) does the same for
`cotton/`, with [`_tag`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/templates.py#L39-L42) computing the `<c-...>` tag a
path answers to — and a component counts as used when a Python string
literal names it, because declared rendering (an agent's
`tool_call_template`, a `render_to_string` call) is rendering.
[`check_no_includes`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/templates.py#L127-L146) (E404) bans `{% include %}`
outright. [`check_no_same_name_pairs`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/templates.py#L149-L177) (E405) forbids
`demos.html` beside `demos/`, and
[`check_surface_folders_have_an_index`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/templates.py#L180-L212) (E406) requires
each `pages/` folder to have an `index.html` or a redirecting bare route.
[`check_root_components_declare_cvars`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/templates.py#L215-L239) (E407) holds
root-level cotton primitives to an explicit `<c-vars>` interface; nested
components inherit page context by design.

## Alpine (E501–E503)

[`check_directive_grammar`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/alpine.py#L27-L51) parses every directive
expression in every template with the same parser the script collector
uses, flagging anything the CSP build cannot evaluate — operators,
arguments, assignments (E501), and `x-model` specifically (E502), whose
setter compiles to an assignment. The stakes are in the rule text: illegal
expressions fail silently to empty, so without the check nothing would
crash when one slipped in.
[`check_data_names_are_registered`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/alpine.py#L54-L79) (E503) collects every
`Alpine.data` registration across all script blocks and flags an
`x-data="name"` no block registers — a component that would silently never
start.

## Call discipline (E601–E606)

These walk module ASTs — [everything except the
tests](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/calls.py#L74-L81) — for call shapes.
[`check_cache_key_literals`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/calls.py#L93-L122) (E601) flags a literal or
f-string first argument to any of [the cache-API
methods](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/calls.py#L9-L21) on a name called `cache`; keys live in
`app/cache.py`. [`check_tasks_queue_on_commit`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/calls.py#L140-L170) (E602)
finds `.delay()`/`.apply_async()` and [walks the parent chain looking for
an enclosing `on_commit` callable](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/calls.py#L125-L137) — a queue
call outside one races the transaction it belongs to.
[`check_signals_connect_in_ready`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/calls.py#L173-L207) (E603) confines
`.connect()` calls and `@receiver` decorators to `apps.py` and
`signals.py`. [`check_writes_live_in_services`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/calls.py#L210-L244) (E604)
flags [model-write method calls](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/calls.py#L23-L30) and [queryset
writes](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/calls.py#L32) in [the read layers](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/calls.py#L34-L43) —
selectors, agents, api, views, tasks, management, templatetags, mcp tools.
[`check_atomic_lives_in_services`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/calls.py#L290-L325) (E605) confines
`transaction.atomic` (as decorator or `with`) to services.
[`check_full_clean_before_save`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/calls.py#L247-L287) (E606) matches receivers
by name within each service function: `row.save()` needs an earlier
`row.full_clean()`. Saves with positional arguments are skipped on purpose —
that shape is `storage.save(name, content)`, not a model save.

## Auth coverage (E701–E703)

[`check_api_routes_declare_auth`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/coverage.py#L25-L46) (E701): every route
served from `api/` carries the `@api_auth` stash, so public is a recorded
decision rather than a forgotten decorator.
[`check_admin_views_require_permission`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/coverage.py#L49-L75) (E702): every
HTML view routed under `admin/` wears `@permission_required`.
[`check_mcp_tools_complete_their_annotations`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/coverage.py#L78-L97) (E703):
every MCP tool sets every `ToolAnnotations` field explicitly, even the ones
that only matter when `readOnlyHint` is false.
