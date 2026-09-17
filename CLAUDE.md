Be minimal.
Don't try to solve problems that don't exist yet.
Don't put comments in the code unless I ask for them.

Rules marked with a check id like (app.E101) are machine-enforced by the
pattern checks in `app/checks/` — `manage check` fails on a violation,
citing the rule. Unmarked rules are judgment.

# Comments, docstrings and tests

- Docstrings are one line. Application code carries no comments.
- **When code feels like it needs explaining, write a test instead.** Name
  the test after the rule it enforces, and make sure it fails when the rule
  is broken — a guard that passes either way has lost the information the
  comment held.
- Tests are the exception to all of the above: their docstrings and comments
  can be as long as they need to be, and are where the reasoning lives —
  why a line of config exists, what breaks without it, what the failure
  looks like.
- **MCP tool docstrings are not docstrings, they are prompts.** A tool's
  docstring is the description sent to the client and read by the model
  deciding whether and how to call it, so it is written for that reader and
  runs as long as it needs to: what the tool is for, when to reach for it,
  and anything the model would otherwise get wrong. One line is right only
  when the tool really is that simple.
- This file records **patterns to follow**, not incidents. A pitfall a test
  can catch belongs in the test.

# Documentation

- **Never edit `docs/`.** The wiki is edited only while the
  document-codebase skill is running, and the skill runs only when the user
  triggers it — directly, or through a skill that names it as a step.
  Never self-invoke it just because a code change made a page
  stale; say the wiki needs a pass and leave the trigger to the user.

# Scratch work

- `local/` is for scratch work and one-off files that don't need to be
  committed — everything in it except its `.gitignore` is ignored.
- `archive/` is the holding pen the old classifier-experiments code was
  moved into — committed, but excluded from lint, tests, and image
  builds.

# Git

- **Don't commit your work.** Leave changes in the working tree until the
  user runs the shipit skill or tells you to commit. When you do commit,
  structure the commits the way the shipit skill prescribes — it is the
  source of truth for how commits are made here. The exception is a cloud
  sandbox, where committing is the only way to hand work back.

# App structure

This is a **mono-app**: all application code lives in the single Django app
`clx.app`. We do not split into multiple Django apps. Instead, we organize
within the app by layer (app.E105), and each layer can be a **package of
domain-grouped modules** rather than a single file.

```
clx/
  settings.py            project settings
  main.py                ASGI entrypoint; mounts Django and the MCP server
  celery.py              Celery app; what `celery -A clx` resolves to
  mcp/                   MCP server — a second service, see below
  app/
    models/              models package, grouped by domain (e.g. models/user.py)
    selectors/           read logic (DB queries), grouped by domain
    services/            write logic / business logic, grouped by domain
    api/                 JSON API layer (thin), one module per surface
      utils/             the API's shared machinery, one module per concern
    tasks/               Celery task layer (thin), grouped by domain
    agents/              chat agent framework + one module per agent
    management/          management commands (thin), one module per command
    templatetags/        template tags; registered as builtins in settings
    views/               HTML view layer (thin), grouped by domain
    exceptions.py        ApplicationError
    middleware.py        ApiErrorMiddleware (JSON error rendering)
    permissions.py       PERMISSIONS + GROUPS definitions
    signals.py           signal handlers, connected in AppConfig.ready() (app.E603)
    urls.py              URL routing
    templates/           our templates — see Templates below
    template_overrides/  templates whose path a package dictates
    src/                 Tailwind input (main.css)
    static/              build output + static assets
```

- **`models` is a module, not a `models.py`.** Group conceptually related
  models into separate files inside `models/` and re-export them from
  `models/__init__.py` (app.E204) so they import as
  `from clx.app.models import User`.
- The same package-per-layer pattern applies to `services/`, `api/`,
  `selectors/`, `tasks/`, and `views/`. Views group by page surface —
  `demos.py`, `admin.py`, and `main.py` as the general bucket (index,
  profile) — with the module carrying the domain, so a surface's landing
  view is `index`, not `demos_index`.

# Code style

The core idea is a strict separation between **business logic** and the
**interfaces** that expose it — endpoints, views, MCP tools, tasks,
management commands. An interface parses input, calls one service or
selector, and renders the result. It holds no logic of its own.

This is plain Django: no DRF, no serializers, no viewsets.

## Where logic goes

Business logic lives in:
- **Services** — anything that writes/mutates (DB, external resources).
- **Selectors** — anything that reads/fetches data.
- **Model `clean()` and simple model properties** — for constraints and
  trivial, non-relational derived values only.

Business logic must NOT live in:
- Endpoints / views (app.E101, app.E604, app.E605)
- Forms
- Model `save()`
- Custom managers / querysets
- Signals

Keep models, endpoints, and views **lean**. Endpoints and views are thin
interfaces: parse input, call a service or selector, return a response.

## Services

- Live in `services/`, grouped by domain.
- Function-based by default; named `<entity>_<action>` (e.g. `user_create`).
- Take **keyword-only arguments** (unless zero or one argument) (app.E205).
- Type-annotated.
- Use classes only for namespacing, shared helpers, or multi-step flows.
- Wrap multi-write operations in `@transaction.atomic`; use
  `transaction.on_commit()` to trigger async work after commit.

## Selectors

- Live in `selectors/`, grouped by domain. A selector follows the same rules
  as a service.
- Named `<entity>_<action>` (e.g. `user_list`). May return querysets, lists,
  or other structures, and may compose other selectors.

## Validation

- Simple, multi-field, non-relational validation → model `clean()`.
- Complex validation, anything spanning relations / extra fetching / multiple
  models → the service.
- Call `full_clean()` inside the service, right before `save()` (app.E606).

## API / views

- **Static or dynamic decides the renderer, not first paint.** Content that
  never changes once drawn is server-rendered. Content that changes —
  created, edited, reordered, deleted, polled — is rendered by Alpine from
  a payload, and a mutation updates that payload in place: a
  `location.reload()` after a successful `api()` call is a bug, and it
  throws away the scroll position of the page it fires on. That payload is
  the view's context, however large — a big context payload is a thin view
  doing its job, and if assembling it gets unwieldy the fix is a selector,
  not an endpoint. The celery demo is the worked example: the beat
  schedule's sentence never changes, so `heartbeat_seconds` renders
  server-side; the jobs list changes constantly, so Alpine draws it from
  the API it polls.
- **Content rendered in two places goes through one renderer**, or the two
  paths drift. `pages/admin/users.html` is the worked example: the table is
  dynamic, so Alpine draws it, and its first page arrives from the same
  endpoint that serves its searches.
- One endpoint per operation; keep them thin.
- Object fetching can happen at the endpoint level, then hand off to
  services/selectors.
- No business logic in this layer.
- API endpoints live in `api/`, one module per surface (e.g. `api/health.py`).
- **Surfaces are the flat files in `api/`; everything they share lives in
  `api/utils/`.** That is the same `utils` the other layers have — the
  layer's shared machinery — and it is a package because it holds more than
  one concern: `authentication.py` for who
  is calling, `ratelimit.py` for how much they may call, `decorators.py` for
  what an endpoint composes them with, `parsing.py` for reading a body.
- `utils/__init__.py` re-exports **only** the names an endpoint uses, so a
  surface imports once and never reaches into a submodule. Anything it
  re-exports is public API; anything it does not is internal. Re-exporting
  an internal erases that boundary. (app.E102)
- A helper moves to its own module in `utils/` once it has a name and its
  own tests. Until then it belongs in an existing one.
- **The machinery's tests own their URLconf.** `tests/urls_api_auth.py`
  declares throwaway endpoints and the tests point at it with
  `pytest.mark.urls`, so what is covered is `api_auth` itself rather than
  whichever demo endpoint happened to use it. The demo surface is designed
  to be deleted; its tests may go with it, and these must not.

## Tasks

Celery, with redis as the broker. `clx/celery.py` holds the app, and the
worker and beat each run as their own service — in compose and in infra —
off the same image as the web process.

- Tasks live in `tasks/`, grouped by domain (e.g. `tasks/demo.py`) and
  re-exported from `tasks/__init__.py`, so interfaces import
  `from clx.app.tasks import <task>`. `autodiscover_tasks()` imports the
  package by name, and registration happens at import — a module
  `__init__.py` does not import silently does not exist, the same failure
  mode as MCP tool modules.
- **A task is an interface**, like an endpoint or an MCP tool: it calls one
  service and holds no logic of its own.
- Task arguments cross the broker as JSON — pass ids, not objects, and
  re-fetch inside the task, doing nothing if the object is gone.
- Services trigger tasks with `transaction.on_commit(lambda: task.delay(...))`,
  never before the write commits. (app.E104, app.E602)
- Periodic work is a `CELERY_BEAT_SCHEDULE` entry in settings naming the
  task by dotted path — the full module path, domain included
  (`clx.app.tasks.demo.demo_heartbeat_task`). Beat resolves that name at
  send time, not startup, so a stale entry fails silently — `test_tasks.py`
  guards against it.

## Agents

The chat engine's pluggable half. `agents/base.py` holds the framework —
`Agent`, `Tool`, `ToolOutput`, `AgentState`, the `AGENTS` registry — and
each agent is one module carrying its agent class, state model, and tools
(`demo.py` is the worked example). Split a shared `tools/` module out
only when a tool is actually used by more than one agent.

- Agents and tools register at import via `__init_subclass__`, and
  `agents/__init__.py` imports each agent module by name — a module it does
  not import silently does not exist, the same failure mode as MCP tool
  modules and celery tasks.
- **Agent and tool docstrings are prompts**, like MCP tool docstrings: the
  tool docstring is the description the model reads when deciding to call
  it, registration raises without one, and they are exempt from the
  one-line rule.
- **A tool is an interface**, like an endpoint or an MCP tool: it may fetch
  objects, but writes go through a service — `check_weather` reads the
  thread and hands its new state to `demo_chat_thread_state_update`. Tools
  receive `thread_id`, never objects, and run synchronously inside the
  celery worker.
- Rendering is declared, not coded: `tool_call_template`,
  `tool_result_template`, and `state_template` name templates under
  `cotton/demos/chat/`, server-rendered and shipped to the page in events;
  `None`
  falls back to a generic card, so a new agent needs no frontend work.
- The turn engine lives in `services/demo.py`. Agents and tools never
  publish events or touch the stream — they compute and return, and the
  runner persists, publishes, and loops.

## Caching

Redis, through Django's cache API — the same instance celery brokers through.

- **Every cache key is a constant in `app/cache.py`** (app.E601), named
  `<THING>_CACHE_KEY`, with its TTL beside it as `<THING>_CACHE_TTL` when it
  has one. Nothing passes a literal string to `cache.get`/`cache.set`. The
  module is also where a key *builder* goes when a key is dynamic — a
  user-scoped key is a function there, not an f-string at the call site.
- **Reads cache lazily, in the selector.** A cached read is a selector like
  any other: return the cached value if it is there, otherwise fetch, set
  with the key's TTL, and return. `selectors/site_config.py` is the model to
  copy.
- **Writes bust, in the service**, with `@busts_cache(KEY, ...)` from
  `services/utils.py`. It runs the service, then drops the keys once the
  surrounding transaction commits — the same `on_commit` discipline as
  queuing a task, and for the same reason: a rolled-back write must not
  evict a value that never changed. A service that invalidates a key it
  does not own is fine; that is what the shared constants are for.
- The pairing is the whole pattern: **a key read by a cached selector must
  be named by every service that writes what it holds.** Nothing else
  expires it inside the TTL.

The singleton `SiteConfig` row is the worked example — `site_config_get`
caches it for an hour, `site_config_update` busts it, and `post_migrate`
creates the row. The `site_config` context processor puts the whole row on
every template context, so a new site-wide setting is a field plus a
migration and nothing else. It is `SiteConfig`, not `Config`, because
`config` is the most overloaded word in a Django project — `AppConfig`,
`ConfigDict`, `model_config` — and the template context is a namespace
where a collision shadows silently instead of raising.

## Search

Elasticsearch, self-hosted, reached through `ELASTICSEARCH_URL`. Postgres
is the source of truth and the index is a **rebuildable projection** of it —
losing the index loses ranking, never data.

- **`app/search.py` owns the index contracts**, the way `cache.py` owns
  cache keys: the shared client, and per index a name builder, the
  mapping, and the document builder. Mapping and builder are two halves of
  one contract, which is why they live in the same file — and the mapping
  sets `dynamic: strict`, so a field the builder emits that the mapping
  does not name fails at index time instead of being silently guessed at.
  Names come from `ELASTICSEARCH_INDEX_PREFIX`, which is what keeps the
  test indices off the dev ones on a shared cluster.
- **Queries are selectors, indexing is a service** — the same read/write
  split as everything else. A search selector takes ids and ranking from
  elasticsearch and hydrates rows from postgres, reordering to match; it
  returns model instances, so nothing downstream ever renders a stale
  document.
- **Sync is the writing service's job**: after its rows commit, it queues
  the reindex task with `transaction.on_commit`, the same discipline as
  every other task. Never signals — a signal fires mid-transaction and
  indexes rows that may roll back.
- **A rebuild is an alias swap.** The reindex service writes a fresh
  physical index, then moves the alias and deletes the replaced index in
  one atomic update, so a mapping change deploys as: change the contract,
  rebuild.
- The index carries only what search needs — a projection, not a mirror
  of the table.

## Templates

Every template is exactly one of four things. To place a piece of markup, ask
the questions in order and stop at the first yes:

1. **Is its path dictated by a package?** → `template_overrides/`
2. **Does a URL render it?** → `templates/pages/`
3. **Is it a frame several pages share?** → `templates/layouts/`
4. Otherwise → `templates/cotton/`

```
templates/
  layouts/             page frames; base.html is the most primitive one
  pages/               one template per view
  cotton/              every reusable or extracted piece
template_overrides/    account/, allauth/, oauth2_provider/, 40x + 500
```

Both directories are in `TEMPLATES["DIRS"]`, `templates` first. Resolution is
by name, so a template in one directory can extend or include one in the other.

### Layouts and pages

- Layouts use Django inheritance, not components — blocks are the right tool
  for "the page fills in the holes". **`layouts/base.html` is the HTML
  skeleton and the most primitive layout**: every other layout extends it,
  fills `{% block content %}`, and exposes its own block for the page
  (`card`, `sections`); a page wanting no chrome extends it directly.
- `base.html` owns the `nav`, `content`, `footer`, `extra_head` and
  `extra_body` blocks. **`nav` and `footer` are opt-in** — empty by
  default, so a page or layout that wants them says so.
- Pages go in `pages/` whatever their file type. `sw.js` and
  `manifest.webmanifest` are pages: a URL renders them. The service worker in
  particular **must** be served from the root, because a service worker only
  controls paths at or below its own URL.
- **A surface with sub-pages is a folder, and its bare route renders the
  folder's `index.html`** (app.E405, app.E406) — `pages/demos/index.html`, never a `demos.html`
  beside a `demos/` folder, so a surface's templates live in one place. A
  surface whose bare route redirects to a sub-page (admin) has no index.

### Components

**There are no partials.** `{% include %}` is not used (app.E404); everything is a cotton
component. Cotton passes the parent context through by default, so it does
everything an include does, and `only` upgrades it to a strict interface.
One mechanism means no decision to make at each extraction.

- `<c-name />` resolves to `cotton/name.html`. Dots are folders and hyphens
  become underscores, so `<c-admin.user-table />` is
  `cotton/admin/user_table.html`.
- **A component lives at the shallowest namespace where all its callers can see
  it.** Start it inside the page's namespace; move it up when a second surface
  needs it. Components at the root of `cotton/` are design-system primitives;
  anything nested belongs to a single page or surface.
- **Nesting means surface ownership, nothing else.** A folder under `cotton/`
  is always a page or surface namespace. Sub-parts of a compound primitive
  flatten to the root with the parent's name as a prefix —
  `cotton/dropdown_item.html` (`<c-dropdown-item />`), never
  `cotton/dropdown/item.html`. Flat sub-parts are root primitives, so the
  components-page guard test forces their documentation automatically.
- Root-level components declare `<c-vars>` and take `only` (app.E407),
  because a shared
  primitive should have an explicit interface. Nested ones inherit page context
  — that is what they are for.
- Leave `COTTON_ENABLE_CONTEXT_ISOLATION` off. Turning it on forces explicit
  attributes everywhere and breaks extracting a chunk of a page for legibility.

Componentize when **any one** of these is true — a single call site is not a
reason to hold back:

- it is used a second time;
- it owns behaviour (an Alpine `x-data` island), so the behaviour gets a name;
- the page template stopped being scannable.

That last one is a real reason on its own. A one-use fragment at
`cotton/dashboard/billing_tab.html` makes no claim of reusability — the
namespace records that it belongs to the dashboard.

### Overrides

`template_overrides/` holds templates **a package asks for by name**. Their
paths are a contract, like a URL, so they are not ours to organise — which is
why they sit outside the placement rule above rather than as an exception to
it.
The directory is also the list of files to re-check when a package is upgraded.

The test is whether something else requests the path. `account/login.html`
qualifies (allauth renders it) and so do `404.html` and the other error
pages (Django's default error views name them). `cotton/account/fields.html`
does not — allauth never requests that path, so it is an ordinary component
that happens to serve those pages.

Overrides still extend our layouts, so a package's pages look like the rest of
the app.

### Cotton configuration

Cotton is registered as `django_cotton.apps.SimpleAppConfig`, **not**
`django_cotton`. The default AppConfig rewrites the `loaders` entry in
`TEMPLATES["OPTIONS"]` and force-wraps them in the cached loader regardless
of `DEBUG`, which silently stops template edits from taking effect until the
process restarts. The loader
and the `builtins` entry are configured by hand in `settings.py` instead, so
the cached loader stays off under `DEBUG`.

Django caches templates in `DEBUG` too, and only `runserver`'s reloader clears
that cache — under uvicorn nothing does. That is why the cached loader is
applied only when `DEBUG` is off.

### CSP and Alpine

The app enforces a strict Content-Security-Policy — `script-src 'self'`, no
nonce, no `unsafe-inline`, no `unsafe-eval` — and the vendored Alpine is the
**CSP build**, whose evaluator resolves only property paths and method
references. Both halves are pinned by `test_csp.py`; the policy lives in
`CONTENT_SECURITY_POLICY` in settings.

- **The page renders no inline scripts at all.** Every line of our JavaScript
  ships in one compiled bundle, `static/js/main.js`, loaded by `base.html`
  before Alpine (a plain event listener registers fine either way, and
  loading first works no matter how Alpine starts).
- Directive expressions are a grammar, not JavaScript (app.E501,
  app.E502, app.E503). Legal: a registered
  name in `x-data`, bare/dot paths in bindings (`x-show="open"`,
  `x-text="job.subtitle"`, truthiness like `x-show="job.children.length"`,
  `$store` paths), and method references in handlers (`@click="close"`).
  Handler references resolve against the **component**, not `$store` — a
  `$store` path renders fine in a binding but silently does nothing as a
  handler, so a panel that talks to a store declares a small component
  whose methods delegate (`setSort(evt) { this.$store.x.setSort(evt) }`).
  Illegal: operators, ternaries, negation, string concatenation, arguments,
  assignments, and `x-model` (its setter compiles to an assignment) — and
  illegal expressions **fail silently to empty**, so nothing crashes when one
  slips in. `:style` is illegal for a second reason (app.E504): Alpine writes a
  string binding through the `style` attribute, which `style-src 'self'`
  blocks — a width that has to move sets the property from the component's own
  JavaScript, where CSSOM is not policed.
- The replacements: getters for computed bindings; enrichment at fetch time
  for list items (`job.isRunning`, `u.downloadUrl`, precomputed label and
  class strings); `:value` + `@input` pairs instead of `x-model`; handlers
  take the event, so per-row arguments travel as data attributes —
  `:data-id="job.id"` on the button, `evt.currentTarget.dataset.id` in the
  method.
- **A component's behaviour lives in the component's own file**, in a
  `{% script %}` block at the bottom, however many times that template
  renders — the collector reads files, not renders, so a primitive used
  twelve times still contributes its registration once.
- **No template syntax inside script bodies.** Django values — URLs, limits,
  per-instance config — cross into JavaScript as data attributes on the
  component's own root element, read from `this.$el.dataset` in `init()`
  (`data-confirm="{{ confirm }}"`). That keeps the block valid JavaScript
  for an editor, and puts every value on the component's interface.
- **Declare every property the component assigns**, with a default, in the
  object the factory returns. Assigning a name in `init()` that the literal
  does not declare does not create it on the component — it falls through
  to an enclosing scope, which the layout supplies and every sibling
  shares. A component rendered more than once on a page then overwrites its
  siblings and the last one rendered wins, silently and only when repeated.
  The same applies to anything derived from those values, since the getter
  reads the shared copy.
- **A store is started by a component, never by itself.** `Alpine.data` is
  lazy — `init()` runs only where an element declares `x-data="name"` — but
  `Alpine.store` calls `init()` eagerly at registration, and the bundle is
  global, so a store that started itself would poll from every page in the
  app. Instead a store exposes an idempotent `start(config)`, and the
  component that owns the surface calls it from its own `init()`, passing
  `this.$el.dataset`. Being idempotent matters because a store is usually
  shared by several components in separate panels.
- Cross-component actions bridge with `$dispatch` plus a listener on the
  receiving root (`@modal-close.stop="close"` — on the teleported wrapper,
  since teleported DOM does not bubble through the component root).
- **Requests go through `api(url, {method, body})`**, declared in
  `base.html`. It attaches the CSRF header, JSON-encodes anything that is
  not `FormData` — which must pass through untouched, or the browser cannot
  set the multipart boundary — and throws the `{"message", "extra"}` error
  `ApiErrorMiddleware` renders, so a call site is a `try`/`catch` over
  `error.message`. A response that is not JSON, like the upload preview
  stream, uses `fetch` directly.
- `frame-ancestors` is `'none'` globally; a response our own pages frame
  relaxes it with `frame_self` from `api/utils/`. `form-action` is omitted
  deliberately — the reasoning lives in `test_csp.py`.

### The script bundle

`{% script %}` marks JavaScript for the bundle. It is a compile-time marker:
it renders nothing, and the browser only ever sees `static/js/main.js`.

```html
{% script %}
<script>
  document.addEventListener("alpine:init", () => {
    Alpine.data("dropdown", () => ({ ... }));
  });
</script>
{% endscript %}
```

- **The body stays wrapped in real `<script>` tags** so an editor keeps
  highlighting it as JavaScript. The tag rejects anything else.
- `manage collectscripts` compiles it, walking the template dirs in order
  and concatenating each block under a `/* origin */` comment. `--watch`
  recompiles on change; the `scripts` compose service runs it in dev and the
  Dockerfile runs it once at build, exactly like the Tailwind CSS build.
  `main.js` is a build artifact and is gitignored, same as `main.css`.
- **The bundle is one script, so every block shares one top-level scope.**
  That is how shared helpers work: `csrfToken()` and `api()` are declared in
  `base.html` and every other block can call them, with no namespace and no
  import. Declare at the top level, but do not *call* at the top level —
  blocks run in path order, while a component's work waits for
  `alpine:init` or an event.
- The collector is the only place that sees every template at once, so it is
  where **name collisions** are caught: registering the same `Alpine.data`
  or `Alpine.store` name, or declaring the same top-level function or
  constant, in two templates fails the build. The second check matters more
  than it appears to: a duplicate declaration is a `SyntaxError`, and one
  `SyntaxError` stops the whole bundle from parsing on every page.
- Compile-time validation happens twice on purpose: the tag raises while the
  page renders (immediate, in front of you), the collector raises for
  templates nothing rendered.

## Theming

The design system is a set of **semantic tokens** defined in the `@theme`
blocks of `clx/app/src/main.css`. Templates use roles, never raw palette
colors — `bg-primary`, not `bg-gray-900`. Everything below the tokens follows
from them, and `/demos/components/` renders the whole theme at a glance, so it
is the visual smoke test after any theme change.

### Color roles

- **primary / primary-hover / primary-foreground** — the action color:
  buttons, links, active states. `-foreground` is the text color placed on it.
- **secondary / secondary-hover / secondary-foreground** — a second brand
  color; defaults to primary until a brand needs one.
- **accent / accent-foreground** — subtle emphasis fills: hover tints on menu
  items and ghost buttons, the neutral badge. `accent-foreground` doubles as
  the interactive-secondary text color (labels, menu items).
- **background / surface** — page vs. raised things (cards, nav, dropdowns).
  Same value today; kept separate so off-white-page-with-white-cards is a
  two-line change.
- **muted / muted-foreground** — placeholder fills and secondary text.
- **foreground** — body and heading text.
- **border / border-strong / ring** — hairlines, input borders and hover
  emphasis, focus.
- **inverse-surface / inverse-foreground / inverse-muted** — the inverted
  dark surfaces: footer, toasts, tooltips, code blocks, the `<html>`
  backdrop.
- **success / warning / danger / info** — status. Each has `-soft` (tinted
  background) and `-soft-foreground` (text on the tint); solid + white
  `-foreground` for filled uses; `danger-hover` exists for danger buttons.
  Borders on soft tints use `border-current/25`, no extra token.

### Other tokens

- **--font-sans / --font-mono / --font-display** — `font-display` is the
  heading face (hero, layout headings) and defaults to the sans stack.
- **--radius-control / --radius-surface** — buttons, inputs, small boxes vs.
  cards and modals.
- **--shadow-card / --shadow-card-hover** — the only two elevations.
- **--spacing-nav** — nav height; gives `h-nav`, `top-nav`, and
  `h-[calc(100dvh-var(--spacing-nav))]`, so the nav and the full-height
  layouts move together.
- **--container-shell** — shared page width (`max-w-shell`) for nav, footer,
  and grid pages.

### Prose

`.content` is the one prose class, and **markdown's output is its structural
contract**: the element set it styles — headings, paragraphs, lists, quotes,
rules, tables, code — is exactly what the renderer can emit, so a rendered
document and a hand-written page are the same markup under the same rules.
That is why the selectors are descendant rather than direct-child: markdown
nests, and a `<p>` inside a `<blockquote>` must still be styled.

Non-prose markup living inside `.content` — component examples, grids, cards —
opts out by carrying its own utilities, which win because Tailwind orders
utilities after components. Nothing else is needed.

Spacing goes through `--prose-block-gap`, `--prose-heading-gap` and
`--prose-subheading-gap`, so a tighter or looser variant is a class that
re-points three variables rather than a second copy of the rule set.

Headings carry `id`s, which is what the content layout's table of contents
reads. It re-scans on any change to the prose, so it follows a live markdown
preview as it is typed.

Hand-written pages write those ids by hand. **Markdown emits them only for
`<c-markdown ids />`**, because a rendered document is usually embedded in a
page rather than being one, and an embedded preview that emitted ids would
put its headings in the host page's table of contents and collide with the
host page's own anchors. The default covers the safe case: forgetting `ids`
on a page that wanted them shows up immediately as an empty table of
contents, where the reverse would be a quiet bug.

### Rebrand checklist

Everything a rebrand touches, in one pass:

1. `@theme` blocks in `src/main.css` — colors, fonts (add `@font-face` or a
   font link in `extra_head`), radii, shadows.
2. `site_name` on the `SiteConfig` row — title, footer, manifest. Change it
   on the admin settings page (or with `site_config_update`); templates
   read `{{ site_config.site_name }}`.
3. `cotton/brand.html` — the hard-coded wordmark, deliberately not read
   from `site_name`, because a real brand replaces this component with its
   own logo.
4. Icon files in `static/icons/` — `favicon.svg`, `apple-touch-icon.png`,
   `icon-192.png`, `icon-512.png`.
5. Hardcoded hex that CSS variables cannot reach: `theme-color` meta in
   `base.html`, `background_color`/`theme_color` in `manifest.webmanifest`
   (match them to `background` / `inverse-surface`).
6. Load `/demos/components/` and review every token and primitive at once.

## MCP

We use `fastmcp` directly rather than a Django integration package — the ones
that exist are unmaintained and pin an old `mcp` SDK.

**`clx/mcp/` is a second service, not an app layer**, so it lives beside
`main.py` rather than inside `app/`. It is mounted as its own Starlette app
and bypasses Django's routing, middleware, auth, CSRF and SSL redirect
entirely. Imports run one way (app.E103) — `clx.mcp` imports `clx.app`, never the
reverse — so the whole feature is `clx/mcp/` plus three lines in
`main.py`, and deleting that directory removes it completely.

- `mcp/server.py` holds the single `FastMCP` instance and installs
  `ToolMiddleware`. `mcp/tools/base.py` holds `MCPTool`, `ToolInputs` and the
  `TOOLS` registry; tools are classes in `mcp/tools/`, one per module.
- A tool sets `name`, declares its inputs, and implements
  `async def __call__(self, arguments)`. The class docstring becomes the
  tool description the client sees, so it is required — `__init_subclass__`
  raises without one. Write it as a prompt for the calling model, not as a
  one-line summary; it is exempt from the docstring rule above.
- **Every tool sets every field of `ToolAnnotations`** (app.E703),
  explicitly, even the
  ones that only matter when `readOnlyHint` is false.
- Register a new tool by importing its module in `mcp/tools/__init__.py`.
  Defining the class registers it in `TOOLS` via `__init_subclass__`, so a
  module nobody imports silently does not exist.
- Tools run in an async context. Anything touching the ORM, cache or storage
  must be wrapped in `sync_to_async` — a sync call raises
  `SynchronousOnlyOperation` at call time, not at startup.
- Keep tools thin and call services/selectors, same as any other interface.
  A tool that composes several service calls is doing work that belongs in
  the service layer, where the other interfaces can reach it too.

### Inputs

- Declare inputs as a `ToolInputs` subclass and set it as the tool's `inputs`.
  `ToolInputs` sets `extra="forbid"`, which is what puts
  `additionalProperties: false` in the generated schema — without it unknown
  arguments validate clean. A tool that takes no arguments omits `inputs`.
- The **JSON Schema is the source of truth**, not the model: `get_input_schema`
  dumps the pydantic model, and `ToolMiddleware` validates arguments against
  that schema with `jsonschema`. A tool whose schema has to be built at runtime
  overrides `get_input_schema` and returns a dict; everything downstream is
  unchanged.
- Because the schema is what gets validated, `__call__` receives the raw
  `arguments` dict. Construct the model inside the body if a tool wants typed
  access.
- Keep inputs flat. A nested or optional model becomes an `anyOf` in the
  schema, and jsonschema then reports `is not valid under any of the given
  schemas` instead of naming the offending field.

### Permissions and errors

- `required_perms` is a tuple of permission strings, empty by default.
  `ToolMiddleware` filters `list_tools` by it *and* enforces it on
  `call_tool` — the same split used in templates and views: hide the control
  from callers who cannot use it, and enforce the permission at the
  destination. `always_listed = True` opts a tool out of the filtering half
  only: everyone sees it, the call check still rejects — the demo tools
  carry one of each so both shapes stay exercised.
- `required_scopes` is the tool-level `scopes=`: the same `API_SCOPES`
  vocabulary the HTTP API gates on, checked against the OAuth token per
  call. There is no MCP-only scope — the resource metadata advertises
  `API_SCOPES`, so a client knows to request them at consent.
- Tool calls are rate limited through `rate_limit_consume`, drawing from
  the **same** per-user and per-scope buckets as token traffic over HTTP —
  a user's aggregate ceiling is actually aggregate. A tool can add its own
  burst budget with a `rate = (limit, seconds)` attribute, the tool-level
  `rate=`.
- `mcp/utils.py` resolves the caller: `current_user()` maps the access token's
  subject to a `User` (or `None`), and `user_has_perms()` checks against it.
- **A tool that needs the caller calls `current_user()`.** It costs a second
  lookup on top of the middleware's permission check, which is the cost of
  not passing request state around.
- **Nothing takes a fastmcp `Context`.** Tools receive `arguments` and nothing
  else, and request-scoped state is not threaded through the call — resolve it
  from the token instead. A tool that genuinely needs the context can reach it
  with `fastmcp.server.dependencies.get_context()` rather than by adding a
  parameter, the same way `mcp/auth.py` reaches the access token.
- Cross-request state — pagination cursors, resumable work — has no
  mechanism here yet. It belongs in a store (redis is already wired up for
  the cache), not on a context object. Add one when a tool actually needs it.
- `ToolMiddleware` owns dispatch, so it also owns the response: results that
  aren't already strings are JSON-dumped into a `ToolResult`. There is no
  automatic structured output derived from return annotations — that is the
  trade for overriding `on_call_tool`.
- `ApplicationError` and Django's `ValidationError` are translated into
  `ToolError`, the same way `ApiErrorMiddleware` renders them for JSON
  clients. Unexpected errors bubble.
- Mounted at `/mcp` in `clx/main.py` over Streamable HTTP, as a Starlette
  route beside the Django app. It bypasses Django's middleware entirely, so it
  is not covered by Django auth, CSRF or the SSL redirect.
- Auth is a `RemoteAuthProvider` in `mcp/server.py`. `mcp/auth.py` verifies
  bearer tokens against django-oauth-toolkit's `AccessToken` model directly,
  rather than calling `/o/introspect/`, which 403s without an
  introspection-scoped caller.
- An unauthenticated call gets a 401 with a `WWW-Authenticate` header
  pointing at the RFC 9728 resource metadata.
- The parent `Starlette` must be given `lifespan=mcp_app.lifespan`; without it
  the session manager never starts.
- Test tools by passing the server object straight to `fastmcp.Client`, which
  connects in-memory. To test as a user, patch
  `clx.mcp.utils.get_access_token` — the one seam every caller goes
  through, so the real lookup and permission check still run. Those tests
  need `django_db(transaction=True)`, because `sync_to_async` runs the ORM on
  another thread with its own connection.

## URL routing

`urls.py` collects patterns into named lists, then dumps them into
`urlpatterns`:

- Each view domain gets its own list, named `<domain>_view_patterns` (e.g.
  `demos_view_patterns`), built from that domain's module in `views/`.
- Service worker and manifest routes go into `pwa_patterns`, kept separate
  from the app's own pages.
- Each API surface gets its own list, named `<surface>_api_patterns` (e.g.
  `health_api_patterns`), built from that surface's module in `api/`.
- **A surface has one name, used verbatim in three places** (app.E301,
  app.E302, app.E303): the interface
  module, its pattern list, and the URL prefix the list is included under —
  `api/users.py`, `users_api_patterns`, `api/users/`; `views/demos.py`,
  `demos_view_patterns`, `demos/`. URL names carry the same surface prefix
  (`users-me`, `demos-jobs`, `admin-user-list`). Surfaces over REST
  collections are plural because their URLs are; the domain register —
  models, services, selectors, tasks — stays singular (`user_create`,
  `demo_docket_import`). The layer a name lives in says where it acts;
  which register it uses says which side it is on.
- A prefix shared by every route in a list is applied where the list is
  included in `urlpatterns` (app.E304), not repeated inside the list itself — e.g.
  `path("api/users/", include(users_api_patterns))` or
  `path("demos/", include(demos_view_patterns))`. A list with no shared
  prefix is spread into `urlpatterns` directly (view lists) or included
  under `api/` (API surfaces).

## Permissions

`permissions.py` defines `PERMISSIONS` and `GROUPS`; the `post_migrate` handler
in `signals.py` creates them:

| Group | `app.manage_admin` | `app.manage_developer` |
| --- | --- | --- |
| `Admin` | yes | no |
| `Developer` | yes | yes |

Guard each layer with the mechanism that belongs to it:

- **Templates** — the built-in `perms` context variable:
  `{% if perms.app.manage_admin %}`. Use it to hide links and controls that
  lead somewhere the user cannot go; it is not a substitute for guarding the
  destination.
- **HTML views** — Django's built-in decorator:
  `@permission_required("app.manage_admin")`. Redirects to login on
  failure. Every view under `admin/` carries it. (app.E702)
- **API endpoints** — the `perms=` argument to `api_auth`:
  `@api_auth(SESSION, TOKEN, perms=[MANAGE_ADMIN])`, using the dotted
  constants from `permissions.py` rather than a hand-typed string, since a
  typo fails closed and silently locks everyone out. It raises
  `PermissionDeniedError`, so the 403 arrives in the same
  `{"message", "extra"}` shape a JSON client gets for every other failure.
  It is an argument rather than a separate decorator for two reasons: it is
  the same kind of declaration as `scopes=`, and a standalone decorator
  would have to be applied *inside* `api_auth` to see a resolved user —
  outside it, a token request would check `AnonymousUser` and 403 everyone.
  Every endpoint under `api/` wears `api_auth`; an endpoint that is open on
  purpose declares it with `@api_auth(PUBLIC)`, which skips authentication
  entirely and composes with nothing, so public is a decision the stash
  records rather than a decorator someone forgot. (app.E701)
- **Permissions bind the user; scopes bind the token.** A permission is a
  fact about who is calling, so it applies to a session and a token alike. A
  scope narrows one credential, so it is checked only for tokens. A token's
  effective rights are its owner's permissions intersected with its own
  scopes.
- **Two credentials, one header, one scope vocabulary.**
  `Authorization: Token pat_...` is a personal API token — a script the
  user runs themselves. `Authorization: Bearer ...` is an OAuth access
  token — a third-party client the user consented to. The scheme names the
  system, so presenting one as the other gets a targeted error instead of
  a generic rejection. Both resolve to the same `Auth` carrying the
  credential's scopes, so every `TOKEN` endpoint accepts either, and both
  systems draw scopes from `API_SCOPES` — which is also what
  `OAUTH2_PROVIDER["SCOPES"]` registers, so the consent screen, the MCP
  resource metadata, and the endpoint checks all speak the same names.
- **MCP tools** — the `required_perms` attribute on the tool class, enforced
  by `ToolMiddleware`. A tool the caller cannot use is also hidden from
  `list_tools` unless it opts out with `always_listed`; `required_scopes`
  holds the OAuth token to the same scopes the API uses.

Codenames use underscores, not hyphens — the `perms` template lookup cannot
resolve a name containing a hyphen.

## Errors

- Raise a domain-level `ApplicationError` for business-rule failures.
- Let unexpected errors bubble up (don't silently swallow them).
- Keep API error responses in a consistent, documented shape.
  `ApiErrorMiddleware` renders `ApplicationError` and `ValidationError`
  as `{"message", "extra"}` with a 400. Endpoints need no decorator —
  raise and let it bubble.
- The middleware only applies to views whose module lives under `api/`,
  so HTML views keep Django's normal error pages. Unexpected errors are
  never caught. `ApplicationError` lives in `app/exceptions.py`, the
  middleware in `app/middleware.py` (last in `MIDDLEWARE`).

## Naming

- Services / selectors: `<entity>_<action>` — for namespacing and
  greppability. (app.E201)
- When a services/selectors file grows large, split it by domain into the
  package rather than letting one file keep growing.
