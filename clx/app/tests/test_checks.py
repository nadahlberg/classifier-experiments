import ast
from pathlib import Path
from typing import Any

import pytest
from django.core.checks import run_checks
from pytest_django.fixtures import SettingsWrapper

from clx.app.checks import (
    alpine,
    calls,
    coverage,
    imports,
    registers,
    surfaces,
    templates,
)
from clx.app.checks.base import ExemptionLog
from clx.app.selectors.codebase import (
    ImportEdge,
    McpToolFact,
    ModuleInfo,
    PatternListFact,
    RouteFact,
    TemplateFact,
)

REPO_ROOT = Path(__file__).parents[3]


def check_ids(*, deploy: bool) -> set[str | None]:
    return {
        message.id for message in run_checks(include_deployment_checks=deploy)
    }


def test_debug_off_without_s3_is_a_deploy_error(
    settings: SettingsWrapper,
) -> None:
    """DEBUG=off + USE_S3=off must fail loudly, not serve 404s.

    With DEBUG off, static() and staticfiles_urlpatterns() contribute no
    URL patterns, and the FileSystemStorage fallback is not reachable
    over HTTP - so a server in this configuration boots cleanly and 404s
    every static asset and upload. The storage health check can't catch
    it either: FileSystemStorage satisfies the save/delete probe in
    exactly the configuration where nothing is served. This check is the
    only signal that fires before the first unstyled page.
    """
    settings.DEBUG = False
    settings.USE_S3 = False

    assert "app.E001" in check_ids(deploy=True)


@pytest.mark.parametrize(
    ("debug", "use_s3"),
    [(True, False), (True, True), (False, True)],
)
def test_every_other_debug_s3_combination_passes(
    settings: SettingsWrapper, debug: bool, use_s3: bool
) -> None:
    """Only one cell of the DEBUG x USE_S3 matrix is broken.

    DEBUG=on serves files itself and USE_S3=on serves them from the
    bucket, so the check must not reject the three working combinations
    - a check that overshoots would block local development or the real
    deployment.
    """
    settings.DEBUG = debug
    settings.USE_S3 = use_s3

    assert "app.E001" not in check_ids(deploy=True)


def test_the_file_serving_check_is_deploy_only(
    settings: SettingsWrapper,
) -> None:
    """The broken combination is only broken for a serving process.

    Management commands run every non-deploy check, and DEBUG=off +
    USE_S3=off is a legitimate environment for migrate or
    makemigrations --check (CI runs the latter with exactly that env).
    Drop deploy=True from the check's registration and this fails - and
    so would every manage command in a prod-like environment.
    """
    settings.DEBUG = False
    settings.USE_S3 = False

    assert "app.E001" not in check_ids(deploy=False)


def test_the_web_container_runs_deploy_checks_before_serving() -> None:
    """The check only guards production if the entrypoint runs it.

    Nothing imports the entrypoint script or the Dockerfile, so nothing
    else fails if `manage check --deploy` is dropped from the boot path
    - the container would go straight back to booting cleanly and
    404ing every asset. This pins the chain: the image CMD runs the
    entrypoint script, and the script runs the check before exec'ing
    uvicorn. Only the web container uses the image CMD - compose dev and
    the celery containers override the command, which is what keeps
    deploy checks off the paths where DEBUG=on makes them misleading.
    """
    dockerfile = (REPO_ROOT / "docker/django/Dockerfile").read_text()
    entrypoint = (REPO_ROOT / "docker/django/entrypoint.sh").read_text()

    assert "docker/django/entrypoint.sh" in dockerfile.split("CMD")[-1]
    assert "manage check --deploy" in entrypoint.split("uvicorn")[0]


# --- Pattern checks -------------------------------------------------------
#
# Each pattern check is a pure assertion over fact tables, so each is
# tested on a synthetic violating table and a synthetic clean one. A
# check that returns the same answer for both has lost the information
# it exists to hold, which is what the parametrized test below pins.


def _module(source: str, path: str = "clx/app/x.py") -> ModuleInfo:
    """A ModuleInfo parsed from inline source, for synthetic fact tables."""
    tree = ast.parse(source)
    return ModuleInfo(
        path=Path(path),
        rel=path,
        source=source,
        lines=source.splitlines(),
        tree=tree,
        functions={
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        },
        classes={
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        },
    )


def _edge(
    module: str, target: str, *, module_level: bool = True
) -> ImportEdge:
    return ImportEdge(
        module=module, target=target, symbol=None, module_level=module_level
    )


def _route(
    *,
    name: str | None = None,
    route: str = "x/",
    module: str = "clx.app.api.x",
    qualname: str = "endpoint",
    has_api_auth: bool = True,
    decorators: tuple[str, ...] = (),
    is_redirect: bool = False,
    template_name: str | None = None,
) -> RouteFact:
    return RouteFact(
        name=name,
        route=route,
        module=module,
        qualname=qualname,
        has_api_auth=has_api_auth,
        decorators=decorators,
        is_redirect=is_redirect,
        template_name=template_name,
    )


def _template_fact(
    name: str,
    *,
    root: str = "templates",
    text: str = "",
    extends: str | None = None,
    used: tuple[str, ...] = (),
    registrations: tuple[str, ...] = (),
    has_cvars: bool = False,
) -> TemplateFact:
    return TemplateFact(
        name=name,
        root=root,
        path=f"clx/app/{root}/{name}",
        text=text,
        extends=extends,
        used_tags=used,
        registrations=registrations,
        has_cvars=has_cvars,
    )


def _list_fact(
    name: str,
    *,
    prefix: str | None,
    routes: tuple[str, ...] = ("",),
    names: tuple[str | None, ...] = (None,),
    modules: tuple[str, ...] = ("clx.app.api.x",),
) -> PatternListFact:
    return PatternListFact(
        name=name, prefix=prefix, routes=routes, names=names, modules=modules
    )


PATTERN_CASES = [
    (
        "E101",
        lambda log: imports.check_layer_imports(
            [_edge("clx.app.selectors.demo", "clx.app.services.demo")],
            log,
        ),
        lambda log: imports.check_layer_imports(
            [_edge("clx.app.selectors.demo", "clx.app.models.demo")],
            log,
        ),
    ),
    (
        "E102",
        lambda log: imports.check_api_utils_boundary(
            [
                _edge(
                    "clx.app.api.demos",
                    "clx.app.api.utils.ratelimit",
                )
            ],
            log,
        ),
        lambda log: imports.check_api_utils_boundary(
            [_edge("clx.app.api.demos", "clx.app.api.utils")], log
        ),
    ),
    (
        "E103",
        lambda log: imports.check_mcp_direction(
            [_edge("clx.app.views.demos", "clx.mcp.server")], log
        ),
        lambda log: imports.check_mcp_direction(
            [_edge("clx.mcp.tools.health", "clx.app.services.health")],
            log,
        ),
    ),
    (
        "E104",
        lambda log: imports.check_lazy_task_imports(
            [_edge("clx.app.services.demo", "clx.app.tasks.demo")],
            log,
        ),
        lambda log: imports.check_lazy_task_imports(
            [
                _edge(
                    "clx.app.services.demo",
                    "clx.app.tasks.demo",
                    module_level=False,
                )
            ],
            log,
        ),
    ),
    (
        "E105",
        # The declared-modules ratchet: a brand-new top-level module in
        # clx/app means new architecture, and the error's job is to
        # force the two registrations that make it real — the checks'
        # layer tables and a CLAUDE.md section. context_processors was
        # caught by this check's very first run against the real tree.
        lambda log: imports.check_app_modules_are_declared(
            {"clx.app.mystery.thing": _module("pass")}, log
        ),
        lambda log: imports.check_app_modules_are_declared(
            {"clx.app.services.demo": _module("pass")}, log
        ),
    ),
    (
        "E201",
        lambda log: registers.check_domain_prefixes(
            {"clx.app.services.demo": _module("def user_create(): pass")},
            log,
        ),
        lambda log: registers.check_domain_prefixes(
            {"clx.app.services.demo": _module("def demo_create(): pass")},
            log,
        ),
    ),
    (
        "E202",
        lambda log: registers.check_task_names(
            {"clx.app.tasks.demo": _module("def demo_reindex(): pass")},
            log,
        ),
        lambda log: registers.check_task_names(
            {"clx.app.tasks.demo": _module("def demo_reindex_task(): pass")},
            log,
        ),
    ),
    (
        "E203",
        lambda log: registers.check_search_contract(
            _module("def demo_index(): pass"), log
        ),
        lambda log: registers.check_search_contract(
            _module(
                "DEMO_MAPPING = {}\n"
                "def demo_index(): pass\n"
                "def demo_document(): pass"
            ),
            log,
        ),
    ),
    (
        "E204",
        # The names come from the running apps registry, the export list
        # from models/__init__.__all__ — so a model whose module was
        # never wired into the re-exports fails here instead of failing
        # at some later import site with a confusing AttributeError.
        lambda log: registers.check_model_reexports(
            ["User"], frozenset(), log
        ),
        lambda log: registers.check_model_reexports(
            ["User"], frozenset({"User"}), log
        ),
    ),
    (
        "E205",
        # Positional params are counted from the AST (posonly + regular);
        # one is allowed — the id-taking task-style entrypoints — and the
        # rest must sit behind the * that CLAUDE.md prescribes.
        lambda log: registers.check_keyword_only_arguments(
            {
                "clx.app.services.demo": _module(
                    "def demo_create(user, name): pass"
                )
            },
            log,
        ),
        lambda log: registers.check_keyword_only_arguments(
            {
                "clx.app.services.demo": _module(
                    "def demo_create(*, user, name): pass\n"
                    "def demo_run(job_id): pass"
                )
            },
            log,
        ),
    ),
    (
        "E301",
        lambda log: surfaces.check_surface_triads(
            [
                _list_fact(
                    "users_api_patterns",
                    prefix="api/user/",
                    modules=("clx.app.api.users",),
                )
            ],
            log,
        ),
        lambda log: surfaces.check_surface_triads(
            [
                _list_fact(
                    "users_api_patterns",
                    prefix="api/users/",
                    modules=("clx.app.api.users",),
                )
            ],
            log,
        ),
    ),
    (
        "E302",
        lambda log: surfaces.check_url_name_prefixes(
            [
                _list_fact(
                    "users_api_patterns", prefix="api/users/", names=("me",)
                )
            ],
            log,
        ),
        lambda log: surfaces.check_url_name_prefixes(
            [
                _list_fact(
                    "users_api_patterns",
                    prefix="api/users/",
                    names=("users-me",),
                )
            ],
            log,
        ),
    ),
    (
        "E303",
        lambda log: surfaces.check_url_name_uniqueness(
            [
                _route(name="index", route="a/"),
                _route(name="index", route="b/"),
            ],
            log,
        ),
        lambda log: surfaces.check_url_name_uniqueness(
            [
                _route(name="index", route="a/"),
                _route(name="other", route="b/"),
            ],
            log,
        ),
    ),
    (
        "E304",
        lambda log: surfaces.check_prefixes_live_at_the_include(
            [
                _list_fact(
                    "health_api_patterns",
                    prefix="api/",
                    routes=("health/",),
                )
            ],
            log,
        ),
        lambda log: surfaces.check_prefixes_live_at_the_include(
            [
                _list_fact(
                    "health_api_patterns", prefix="api/health/", routes=("",)
                )
            ],
            log,
        ),
    ),
    (
        "E401",
        lambda log: templates.check_pages_are_routed(
            [_template_fact("pages/dead.html")], frozenset(), log
        ),
        lambda log: templates.check_pages_are_routed(
            [_template_fact("pages/index.html")],
            frozenset({"pages/index.html"}),
            log,
        ),
    ),
    (
        "E402",
        lambda log: templates.check_layouts_are_extended(
            [_template_fact("layouts/unused.html")], log
        ),
        lambda log: templates.check_layouts_are_extended(
            [
                _template_fact("layouts/base.html"),
                _template_fact(
                    "pages/index.html", extends="layouts/base.html"
                ),
            ],
            log,
        ),
    ),
    (
        "E403",
        lambda log: templates.check_components_are_used(
            [_template_fact("cotton/orphan.html")], frozenset(), log
        ),
        # A component is used when a template carries its tag OR when a
        # Python string literal names it — declared rendering (a
        # render_to_string call, a template path stored on a class) is
        # rendering, so a template only Python knows about is not dead
        # markup.
        lambda log: templates.check_components_are_used(
            [
                _template_fact("cotton/button.html"),
                _template_fact("pages/index.html", used=("c-button",)),
                _template_fact("cotton/tool_card.html"),
            ],
            frozenset({"cotton/tool_card.html"}),
            log,
        ),
    ),
    (
        "E404",
        lambda log: templates.check_no_includes(
            [
                _template_fact(
                    "pages/index.html", text='{% include "partial.html" %}'
                )
            ],
            log,
        ),
        lambda log: templates.check_no_includes(
            [_template_fact("pages/index.html", text="<c-partial />")], log
        ),
    ),
    (
        "E405",
        lambda log: templates.check_no_same_name_pairs(
            [
                _template_fact("pages/demos.html"),
                _template_fact("pages/demos/celery.html"),
            ],
            log,
        ),
        lambda log: templates.check_no_same_name_pairs(
            [
                _template_fact("pages/demos/index.html"),
                _template_fact("pages/demos/celery.html"),
            ],
            log,
        ),
    ),
    (
        "E406",
        lambda log: templates.check_surface_folders_have_an_index(
            [_template_fact("pages/admin/settings.html")], [], log
        ),
        lambda log: templates.check_surface_folders_have_an_index(
            [_template_fact("pages/admin/settings.html")],
            [_route(route="admin/", is_redirect=True)],
            log,
        ),
    ),
    (
        "E407",
        lambda log: templates.check_root_components_declare_cvars(
            [_template_fact("cotton/naked.html")], log
        ),
        lambda log: templates.check_root_components_declare_cvars(
            [_template_fact("cotton/naked.html", has_cvars=True)], log
        ),
    ),
    (
        "E501",
        lambda log: alpine.check_directive_grammar(
            [
                _template_fact(
                    "pages/x.html", text='<div x-show="a && b"></div>'
                )
            ],
            log,
        ),
        lambda log: alpine.check_directive_grammar(
            [
                _template_fact(
                    "pages/x.html", text='<div x-show="job.isRunning"></div>'
                )
            ],
            log,
        ),
    ),
    (
        "E502",
        lambda log: alpine.check_directive_grammar(
            [_template_fact("pages/x.html", text='<input x-model="q">')], log
        ),
        lambda log: alpine.check_directive_grammar(
            [
                _template_fact(
                    "pages/x.html",
                    text='<input :value="q" @input="search">',
                )
            ],
            log,
        ),
    ),
    (
        "E503",
        lambda log: alpine.check_data_names_are_registered(
            [_template_fact("pages/x.html", text='<div x-data="ghost">')],
            log,
        ),
        lambda log: alpine.check_data_names_are_registered(
            [
                _template_fact(
                    "pages/x.html",
                    text='<div x-data="widget">',
                    registrations=("widget",),
                )
            ],
            log,
        ),
    ),
    (
        "E504",
        lambda log: alpine.check_no_style_bindings(
            [
                _template_fact(
                    "pages/x.html", text='<span :style="barStyle"></span>'
                )
            ],
            log,
        ),
        lambda log: alpine.check_no_style_bindings(
            [
                _template_fact(
                    "pages/x.html", text='<span :class="barClass"></span>'
                )
            ],
            log,
        ),
    ),
    (
        "E601",
        lambda log: calls.check_cache_key_literals(
            {
                "clx.app.selectors.demo": _module(
                    'def demo_get():\n    return cache.get("literal")'
                )
            },
            log,
        ),
        lambda log: calls.check_cache_key_literals(
            {
                "clx.app.selectors.demo": _module(
                    "def demo_get():\n    return cache.get(DEMO_CACHE_KEY)"
                )
            },
            log,
        ),
    ),
    (
        "E602",
        lambda log: calls.check_tasks_queue_on_commit(
            {
                "clx.app.services.demo": _module(
                    "def demo_run():\n    demo_task.delay()"
                )
            },
            log,
        ),
        lambda log: calls.check_tasks_queue_on_commit(
            {
                "clx.app.services.demo": _module(
                    "def demo_run():\n"
                    "    transaction.on_commit(lambda: demo_task.delay())"
                )
            },
            log,
        ),
    ),
    (
        "E603",
        lambda log: calls.check_signals_connect_in_ready(
            {"clx.app.services.demo": _module("post_save.connect(handler)")},
            log,
        ),
        lambda log: calls.check_signals_connect_in_ready(
            {"clx.app.apps": _module("post_migrate.connect(handler)")},
            log,
        ),
    ),
    (
        "E604",
        lambda log: calls.check_writes_live_in_services(
            {
                "clx.app.selectors.demo": _module(
                    "def demo_get():\n    Demo.objects.create()"
                )
            },
            log,
        ),
        lambda log: calls.check_writes_live_in_services(
            {
                "clx.app.selectors.demo": _module(
                    "def demo_get():\n    return Demo.objects.filter()"
                )
            },
            log,
        ),
    ),
    (
        "E605",
        lambda log: calls.check_atomic_lives_in_services(
            {
                "clx.app.views.demos": _module(
                    "@transaction.atomic\ndef page(request): pass"
                )
            },
            log,
        ),
        lambda log: calls.check_atomic_lives_in_services(
            {
                "clx.app.services.demo": _module(
                    "@transaction.atomic\ndef demo_create(): pass"
                )
            },
            log,
        ),
    ),
    (
        "E606",
        # Receiver-matched by name and ordered by line: row.save() only
        # passes when row.full_clean() ran earlier in the same function.
        # Saves with positional args are skipped on purpose — that shape
        # is storage.save(name, content), not a model save. This check is
        # why api_token_touch full_cleans its last_used_at stamp: the
        # touch-interval guard already throttles that write, so the
        # validation costs one round per interval, not one per request.
        lambda log: calls.check_full_clean_before_save(
            {
                "clx.app.services.demo": _module(
                    "def demo_create():\n    row = Demo()\n    row.save()"
                )
            },
            log,
        ),
        lambda log: calls.check_full_clean_before_save(
            {
                "clx.app.services.demo": _module(
                    "def demo_create():\n"
                    "    row = Demo()\n"
                    "    row.full_clean()\n"
                    "    row.save()\n"
                    "def demo_store(storage, content):\n"
                    "    storage.save('name', content)"
                )
            },
            log,
        ),
    ),
    (
        "E701",
        lambda log: coverage.check_api_routes_declare_auth(
            [_route(has_api_auth=False)], log
        ),
        lambda log: coverage.check_api_routes_declare_auth(
            [_route(has_api_auth=True)], log
        ),
    ),
    (
        "E702",
        lambda log: coverage.check_admin_views_require_permission(
            [
                _route(
                    module="clx.app.views.admin",
                    route="admin/settings/",
                    decorators=(),
                )
            ],
            log,
        ),
        lambda log: coverage.check_admin_views_require_permission(
            [
                _route(
                    module="clx.app.views.admin",
                    route="admin/settings/",
                    decorators=('@permission_required("app.manage_admin")',),
                )
            ],
            log,
        ),
    ),
    (
        "E703",
        lambda log: coverage.check_mcp_tools_complete_their_annotations(
            [McpToolFact(name="x", missing_annotations=("readOnlyHint",))],
            log,
        ),
        lambda log: coverage.check_mcp_tools_complete_their_annotations(
            [McpToolFact(name="x", missing_annotations=())], log
        ),
    ),
]


@pytest.mark.parametrize(
    ("check_id", "violating", "clean"),
    PATTERN_CASES,
    ids=[case[0] for case in PATTERN_CASES],
)
def test_every_pattern_check_fires_on_a_violation(
    check_id: str, violating: Any, clean: Any
) -> None:
    """Each check flags its synthetic violation and passes its clean twin.

    A guard that passes either way has lost the information it held, so
    every assertion function is exercised on a fact table that breaks
    its rule and one that keeps it. When a check's logic drifts — a
    renamed layer, a loosened regex — this is the test that names it.
    """
    messages = violating(ExemptionLog({}))

    assert [message.id for message in messages] == [f"app.{check_id}"]
    assert clean(ExemptionLog({})) == []


@pytest.mark.parametrize(
    ("check_id", "violating", "clean"),
    PATTERN_CASES,
    ids=[case[0] for case in PATTERN_CASES],
)
def test_check_messages_cite_the_rule_they_enforce(
    check_id: str, violating: Any, clean: Any
) -> None:
    """Every violation message quotes CLAUDE.md in its hint.

    The self-teaching property is the point of the suite: a violation
    produces the rule it broke, not just a symptom, so the error is the
    documentation. A check whose hint stops citing the rule degrades
    into an opaque prohibition.
    """
    for message in violating(ExemptionLog({})):
        assert message.hint and message.hint.startswith('CLAUDE.md: "')


@pytest.mark.parametrize(
    ("check_id", "violating", "clean"),
    PATTERN_CASES,
    ids=[case[0] for case in PATTERN_CASES],
)
def test_an_exemption_silences_exactly_its_violation(
    check_id: str, violating: Any, clean: Any
) -> None:
    """An EXEMPTIONS entry suppresses the flagged ident and is not stale.

    The escape hatch must be precise: exempting the one flagged ident
    silences that message, counts as used, and leaves nothing else
    suppressed. This also pins that every check routes its violations
    through the log rather than returning them unconditionally.
    """
    flagged = violating(ExemptionLog({}))
    ident = flagged[0].obj

    log = ExemptionLog({check_id: frozenset({str(ident)})})
    silenced = violating(log)

    assert silenced == []
    assert log.stale() == []


def test_a_stale_exemption_is_itself_an_error() -> None:
    """An exemption matching nothing produces app.E801.

    Without this the EXEMPTIONS map only ever grows: entries whose
    violations were long since fixed would sit as silent grants waiting
    to hide the next real violation at the same ident.
    """
    log = ExemptionLog({"E101": frozenset({"gone -> nowhere"})})

    stale = log.stale()

    assert [message.id for message in stale] == ["app.E801"]


def test_the_real_codebase_produces_no_pattern_messages() -> None:
    """The tree the suite ships with is clean, with an empty EXEMPTIONS.

    This is the integration pin: every assertion runs over the real
    fact tables and none fires. It is deliberately not marked
    django_db — pytest-django blocks database access for unmarked
    tests, so this test failing on a database touch is the DB-free
    guarantee below failing first.
    """
    from clx.app.checks import check_patterns
    from clx.app.checks.base import EXEMPTIONS

    assert check_patterns(None) == []
    assert EXEMPTIONS == {}


def test_pattern_checks_touch_no_database() -> None:
    """Building the fact tables opens no database connection.

    System checks run on every management command, including migrate on
    a fresh database — a fact build that queried would crash exactly
    when the schema does not exist yet. pytest-django raises on any
    database access in a test not marked django_db, so the plain call
    is the proof.
    """
    from clx.app.selectors.codebase import codebase_facts

    assert codebase_facts().modules
