from collections.abc import Sequence
from typing import Any

from django.apps import AppConfig
from django.core.checks import CheckMessage, register

from clx.app.checks import (
    alpine,
    calls,
    coverage,
    deploy,
    imports,
    registers,
    surfaces,
    templates,
)
from clx.app.checks.base import ExemptionLog

__all__ = ["check_patterns", "deploy"]


@register("patterns")
def check_patterns(
    app_configs: Sequence[AppConfig] | None, **kwargs: Any
) -> list[CheckMessage]:
    """Every architecture-pattern assertion, over one extraction pass."""
    from django.apps import apps

    from clx.app import models as models_package
    from clx.app.selectors.codebase import codebase_facts

    facts = codebase_facts()
    log = ExemptionLog()
    search = facts.modules["clx.app.search"]
    model_names = sorted(
        model.__name__ for model in apps.get_app_config("app").get_models()
    )
    exported = frozenset(models_package.__all__)
    messages = [
        *imports.check_layer_imports(facts.import_edges, log),
        *imports.check_api_utils_boundary(facts.import_edges, log),
        *imports.check_mcp_direction(facts.import_edges, log),
        *imports.check_lazy_task_imports(facts.import_edges, log),
        *imports.check_app_modules_are_declared(facts.modules, log),
        *registers.check_domain_prefixes(facts.modules, log),
        *registers.check_task_names(facts.modules, log),
        *registers.check_model_reexports(model_names, exported, log),
        *registers.check_keyword_only_arguments(facts.modules, log),
        *registers.check_search_contract(search, log),
        *surfaces.check_surface_triads(facts.pattern_lists, log),
        *surfaces.check_url_name_prefixes(facts.pattern_lists, log),
        *surfaces.check_url_name_uniqueness(facts.routes, log),
        *surfaces.check_prefixes_live_at_the_include(facts.pattern_lists, log),
        *templates.check_pages_are_routed(
            facts.templates, facts.rendered, log
        ),
        *templates.check_layouts_are_extended(facts.templates, log),
        *templates.check_components_are_used(
            facts.templates, facts.template_strings, log
        ),
        *templates.check_no_includes(facts.templates, log),
        *templates.check_no_same_name_pairs(facts.templates, log),
        *templates.check_surface_folders_have_an_index(
            facts.templates, facts.routes, log
        ),
        *templates.check_root_components_declare_cvars(facts.templates, log),
        *alpine.check_directive_grammar(facts.templates, log),
        *alpine.check_data_names_are_registered(facts.templates, log),
        *alpine.check_no_style_bindings(facts.templates, log),
        *calls.check_cache_key_literals(facts.modules, log),
        *calls.check_tasks_queue_on_commit(facts.modules, log),
        *calls.check_signals_connect_in_ready(facts.modules, log),
        *calls.check_writes_live_in_services(facts.modules, log),
        *calls.check_atomic_lives_in_services(facts.modules, log),
        *calls.check_full_clean_before_save(facts.modules, log),
        *coverage.check_api_routes_declare_auth(facts.routes, log),
        *coverage.check_admin_views_require_permission(facts.routes, log),
        *coverage.check_mcp_tools_complete_their_annotations(
            facts.mcp_tools, log
        ),
    ]
    messages.extend(log.stale())
    return messages
