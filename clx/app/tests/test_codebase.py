"""The codebase explorer's inventory: complete, resolvable, and honest.

The inventory is rebuilt from the running process on every request, so
nothing registers cards by hand. Each test here pins the completeness
guarantee that makes that trustworthy: a new module, route, task, tool,
or component must show up on its own, every emitted cross-reference must
point at a card that exists, and every source location must point into a
real file. When one of these fails, the extractor has drifted from the
codebase it claims to describe.
"""

from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.test import Client
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from clx.app.models import User
from clx.app.selectors.codebase import (
    EXCLUDED_VIEW_MODULES,
    REPO_ROOT,
    _dict_key_lines,
    _in_package,
    _Inventory,
    codebase_inventory,
)
from clx.app.services.user import user_create
from clx.celery import app as celery_app

APP_DIR = Path(settings.BASE_DIR) / "app"

BACKEND_PACKAGES = ("models", "selectors", "services", "tasks")

Inventory = list[dict[str, Any]]


@pytest.fixture(scope="module")
def inventory() -> Inventory:
    """One build of the inventory, shared by every test in this module."""
    return codebase_inventory()


def _routes(patterns: list[Any], prefix: str) -> list[tuple[str, Any]]:
    """Every (route, callback) pair the resolver serves."""
    found: list[tuple[str, Any]] = []
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            found.extend(
                _routes(pattern.url_patterns, prefix + str(pattern.pattern))
            )
        elif isinstance(pattern, URLPattern):
            found.append((prefix + str(pattern.pattern), pattern.callback))
    return found


def test_inventory_covers_every_url_route(inventory: Inventory) -> None:
    """Every route the resolver serves appears on an endpoint or view card.

    The URL walk is what makes the explorer's routing section trustworthy:
    a new route that the walk misclassifies or drops would silently vanish
    from the page. File-serving patterns are the one deliberate exclusion,
    mirrored here from the selector's own constant so the two cannot
    drift apart.
    """
    covered: set[str] = set()
    for card in inventory:
        if card["layer"] in ("endpoint", "view"):
            covered.update(card["details"]["route"].split(" · "))

    routes = _routes(get_resolver().url_patterns, "")
    assert routes
    for route, callback in routes:
        if getattr(callback, "__module__", "") in EXCLUDED_VIEW_MODULES:
            continue
        assert route in covered, route


def test_external_routes_keep_their_own_configuration(
    inventory: Inventory,
) -> None:
    """Routes served by distinct instances of one external view class stay
    distinct cards.

    sw.js and manifest.webmanifest are both TemplateView.as_view with
    different initkwargs. Grouping externals by view class rather than by
    callback would merge them into one card claiming the first instance's
    template and content type for both, and the manifest's page card would
    silently lose its "Rendered by" link — wrong data, nothing failing.
    """
    by_route = {
        card["details"]["route"]: card
        for card in inventory
        if card["layer"] == "view"
    }
    sw = by_route["sw.js"]
    manifest = by_route["manifest.webmanifest"]

    assert sw["id"] != manifest["id"]
    assert sw["details"]["template_name"] == "pages/sw.js"
    assert manifest["details"]["template_name"] == "pages/manifest.webmanifest"

    pages = {card["id"] for card in inventory if card["layer"] == "page"}
    for card in (sw, manifest):
        rendered = [
            ref["id"] for ref in card["refs"] if ref["kind"] == "renders"
        ]
        assert rendered and rendered[0] in pages, card["id"]


def test_inventory_covers_every_backend_module(
    inventory: Inventory,
) -> None:
    """Every module in the four backend packages contributes cards.

    The walk is filesystem-driven, so adding models/billing.py or
    services/billing.py must surface its contents with no registration
    step. A module that stops contributing means the package walk lost it
    — the exact drift an auto-generated explorer must never have.
    """
    paths = {card["path"] for card in inventory if card["path"]}
    for package in BACKEND_PACKAGES:
        modules = [
            module
            for module in sorted((APP_DIR / package).glob("*.py"))
            if module.stem != "__init__"
        ]
        assert modules, package
        for module in modules:
            rel = module.resolve().relative_to(REPO_ROOT).as_posix()
            assert rel in paths, rel


def test_inventory_covers_every_registered_task(
    inventory: Inventory,
) -> None:
    """Every celery task registration has a card.

    The registry is the runtime truth the explorer promises to reflect: a
    task module that tasks/__init__.py imports must surface. If this fails
    the registry walk went stale while the registry kept working.
    """
    task_names = {
        card["details"]["task"]
        for card in inventory
        if card["layer"] == "task"
    }
    registered = [name for name in celery_app.tasks if name.startswith("clx.")]
    assert registered
    for name in registered:
        assert name in task_names, name


def test_inventory_covers_every_registered_mcp_tool(
    inventory: Inventory,
) -> None:
    """Every registered MCP tool has a card.

    The deferred import mirrors the selector's own ImportError guard:
    CLAUDE.md promises that deleting clx/mcp/ removes the feature
    completely, and a module-level import here would instead error this
    whole file at collection. While mcp/ exists, though, every tool in
    TOOLS must surface.
    """
    base = pytest.importorskip("clx.mcp.tools.base")

    tool_names = {
        card["name"] for card in inventory if card["layer"] == "mcp-tool"
    }
    assert base.TOOLS
    for name in base.TOOLS:
        assert name in tool_names, name


def test_inventory_covers_every_cotton_component(
    inventory: Inventory,
) -> None:
    """Every cotton template has a component card.

    Components are enumerated from the filesystem, the same way the
    components-page guard test enumerates primitives, so a new component
    appears in the explorer the moment its file exists.
    """
    component_paths = {
        card["path"] for card in inventory if card["layer"] == "component"
    }
    files = sorted((APP_DIR / "templates" / "cotton").rglob("*.html"))
    assert files
    for file in files:
        rel = file.resolve().relative_to(REPO_ROOT).as_posix()
        assert rel in component_paths, rel


def test_inventory_refs_all_resolve(inventory: Inventory) -> None:
    """Card ids are unique and every emitted ref points at a real card.

    The client resolves refs with a single id lookup and builds the
    reverse index from them, so one dangling id turns into a silently
    missing link on both cards. Structural refs are built from the
    inventory's own lookups; this pins that no builder emits an id the
    payload does not contain.
    """
    ids = [card["id"] for card in inventory]
    assert len(ids) == len(set(ids))
    known = set(ids)
    for card in inventory:
        for ref in card["refs"]:
            assert ref["id"] in known, (card["id"], ref)


def test_references_resolve_through_private_helpers(
    inventory: Inventory,
) -> None:
    """A private helper's references belong to its public callers.

    The on_commit discipline makes module-local helpers the natural home
    for task queueing (_dispatch and _queue_reindex in services/demo.py),
    and helpers are not cards themselves — so a walk that stopped at the
    function body would leave every "queues" edge in the app silently
    empty while the labels shipped anyway. demo_job_run queues only
    through _dispatch; its card carrying the edge is what pins the
    expansion.
    """
    by_id = {card["id"]: card for card in inventory}
    card = by_id["service:clx/app/services/demo.py:demo_job_run"]
    kinds = {(ref["kind"], by_id[ref["id"]]["name"]) for ref in card["refs"]}

    assert ("queues", "demo_job_execute_task") in kinds


def test_cache_key_references_claim_no_direction(
    inventory: Inventory,
) -> None:
    """A cache-key reference says "uses", never "reads" or "writes".

    An import scan cannot tell a read from a write: demo_heartbeat only
    ever writes its key, and under a "reads" label its card inverted the
    reader/writer distinction the caching pattern documents. "uses" plus
    the stash-backed "busts" is everything the extractor actually knows.
    """
    by_id = {card["id"]: card for card in inventory}
    heartbeat = by_id["service:clx/app/services/demo.py:demo_heartbeat"]

    assert "uses" in {ref["kind"] for ref in heartbeat["refs"]}
    for card in inventory:
        for ref in card["refs"]:
            assert ref["kind"] not in ("reads", "writes"), card["id"]


def test_search_index_cards_carry_both_halves_of_the_contract(
    inventory: Inventory,
) -> None:
    """A search-index card names its document builder, not just its alias.

    CLAUDE.md calls the mapping and the builder two halves of one
    contract, and the card finds the builder by naming convention
    ({base}_index → {base}_document). That lookup is exactly what once
    drifted — a document builder whose prefix disagreed with its index
    function left the card showing half the contract with nothing
    failing. This makes the drift loud.
    """
    cards = [card for card in inventory if card["layer"] == "search-index"]
    assert cards
    for card in cards:
        assert "document builder" in card["details"], card["id"]


def test_inventory_lines_point_into_real_files(
    inventory: Inventory,
) -> None:
    """Every card's path is a real repo file and its line is inside it.

    The detail pane renders path:line as the copyable source reference,
    so a wrong path or an out-of-range line means the AST pass and the
    runtime object disagree about where something lives.
    """
    line_counts: dict[str, int] = {}
    for card in inventory:
        if card["path"] is None:
            assert card["line"] is None, card["id"]
            continue
        file = REPO_ROOT / card["path"]
        assert file.is_file(), card["id"]
        if card["line"] is not None:
            if card["path"] not in line_counts:
                line_counts[card["path"]] = len(file.read_text().splitlines())
            assert 1 <= card["line"] <= line_counts[card["path"]], card["id"]


def test_the_bundles_async_helpers_get_script_cards(
    inventory: Inventory,
) -> None:
    """An `async function` declared at the bundle's top level gets a card.

    The script cards are built from the same DECLARATION regex the
    collector uses, so a keyword the regex misses fails twice at once: the
    declaration has no card here, and the collector's duplicate guard is
    blind to a second copy of it. base.html's api() helper is the standing
    example — before the regex knew `async function`, the app's central
    request helper was invisible to the explorer while csrfToken beside it
    showed up fine.
    """
    card = next(
        (
            card
            for card in inventory
            if card["layer"] == "script" and card["name"] == "api"
        ),
        None,
    )

    assert card is not None
    assert card["details"]["kind"] == "async function"


def test_an_annotated_dict_keeps_its_key_lines(tmp_path: Path) -> None:
    """A type annotation on a scanned dict must not drop its key lines.

    Annotating a module-level dict turns its ast.Assign into an
    ast.AnnAssign, and a scan that only handles the former silently
    returns no lines: every permission, group, scope, and beat card built
    from that dict loses its line, the detail panel's copyable path:line
    chip degrades to just the path, and the lines-point-into-real-files
    test above still passes because it allows None. Adding a perfectly
    reasonable `dict[str, str]` annotation to PERMISSIONS is all it takes,
    which is why both assignment forms must yield the same answer.
    """
    module = tmp_path / "annotated.py"
    module.write_text(
        "PERMISSIONS: dict[str, str] = {\n"
        '    "one": "a",\n'
        '    "two": "b",\n'
        "}\n"
    )

    info = _Inventory().module(str(module))

    assert _dict_key_lines(info, "PERMISSIONS") == {"one": 2, "two": 3}


def test_a_module_sharing_a_package_prefix_is_outside_it() -> None:
    """Package membership needs a dot boundary, not a bare prefix match.

    classify() attributes imported symbols to layers by their module, and
    with a bare startswith a future sibling like clx.app.services_billing
    would match clx.app.services — its symbols would be attributed to
    the wrong layer and mint refs to card ids that do not exist, which
    attach_references drops silently, so the edges would just vanish.
    """
    assert _in_package("clx.app.services", "clx.app.services")
    assert _in_package("clx.app.services.demo", "clx.app.services")
    assert not _in_package("clx.app.services_billing", "clx.app.services")


def test_a_signal_card_never_claims_to_be_unconnected(
    inventory: Inventory,
) -> None:
    """No signal card carries an unconnected flag.

    The connection scan only walks django.db.models.signals and
    django.core.signals, so it can prove a receiver is connected but never
    that it is not — a receiver wired to an auth or allauth signal is live
    while invisible to the scan. An earlier version flagged those
    "unconnected", asserting something false; the card now shows what the
    scan found and stays silent about what it cannot see.
    """
    for card in inventory:
        if card["layer"] == "signal":
            assert not any(
                chip["label"] == "unconnected" for chip in card["chips"]
            ), card["id"]


@pytest.mark.django_db
def test_the_codebase_page_requires_the_admin_permission() -> None:
    """The page embeds the application's own source, so it holds the same
    line the admin API endpoints hold for their payloads — but as an HTML
    view its guard is permission_required, which answers with a redirect
    to login rather than a JSON error. Anonymous and signed-in-but-
    unprivileged callers must both bounce. This fails if the decorator is
    dropped from the view, which would hand every account the inventory.
    """
    assert Client().get("/admin/codebase/", secure=True).status_code == 302

    curious = Client()
    curious.force_login(user_create(email="curious@example.com"))

    assert curious.get("/admin/codebase/", secure=True).status_code == 302


@pytest.mark.django_db
def test_the_codebase_page_renders_the_explorer(admin_user: User) -> None:
    """The tab renders the three Alpine islands and embeds the inventory.

    The payload is fully known at request time and never refetched, so it
    is context data, crossing to the store as a json_script block rather
    than through an endpoint. The render must guarantee two things: the
    islands are present to consume it, and the embedded payload describes
    the very view that served it — if that card id is missing, the URL
    walk went blind to the page the explorer lives on.
    """
    client = Client()
    client.force_login(admin_user)

    response = client.get("/admin/codebase/", secure=True)

    assert response.status_code == 200
    html = response.content.decode()
    assert 'x-data="codebaseExplorer"' in html
    assert 'x-data="codebaseToolbar"' in html
    assert 'x-data="codebaseDetail"' in html
    assert 'id="codebase-inventory"' in html
    assert "view:clx/app/views/admin.py:codebase" in html
