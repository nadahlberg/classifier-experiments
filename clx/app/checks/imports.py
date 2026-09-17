from collections.abc import Mapping, Sequence

from django.core.checks import CheckMessage

from clx.app.checks.base import ExemptionLog, pattern_error
from clx.app.selectors.codebase import ImportEdge, ModuleInfo, _in_package

DECLARED_APP_MODULES = {
    "models",
    "selectors",
    "services",
    "tasks",
    "api",
    "views",
    "management",
    "templatetags",
    "apps",
    "cache",
    "checks",
    "context_processors",
    "exceptions",
    "middleware",
    "permissions",
    "scripts",
    "search",
    "signals",
    "urls",
    "tests",
}

LAYER_PACKAGES = {
    "models": "clx.app.models",
    "selectors": "clx.app.selectors",
    "services": "clx.app.services",
    "tasks": "clx.app.tasks",
    "api": "clx.app.api",
    "views": "clx.app.views",
    "management": "clx.app.management",
    "mcp-tools": "clx.mcp.tools",
}

ALLOWED_IMPORTS = {
    "models": {"models"},
    "selectors": {"models", "selectors"},
    "services": {"models", "selectors", "services", "tasks"},
    "tasks": {"models", "selectors", "services", "tasks"},
    "api": {"models", "selectors", "services", "api"},
    "views": {"models", "selectors", "services", "views"},
    "management": {"models", "selectors", "services", "management"},
    "mcp-tools": {"models", "selectors", "services", "mcp-tools"},
}

RULES = {
    "E101": (
        "The core idea is a strict separation between business logic and "
        "the interfaces that expose it — selectors read, services write, "
        "and interfaces never import each other."
    ),
    "E102": (
        "utils/__init__.py re-exports only the names an endpoint uses, so "
        "a surface imports once and never reaches into a submodule."
    ),
    "E103": (
        "Imports run one way — clx.mcp imports clx.app, never the reverse."
    ),
    "E104": (
        "Services trigger tasks with transaction.on_commit, never before "
        "the write commits — the tasks import stays inside the function."
    ),
    "E105": (
        "We organize within the app by layer — a new top-level module in "
        "clx/app is new architecture, so declare it in the checks' "
        "layer tables and give it ground rules in CLAUDE.md."
    ),
}


def _layer(module: str) -> str | None:
    """The layer a module belongs to, or None for wiring and machinery."""
    for layer, package in LAYER_PACKAGES.items():
        if _in_package(module, package):
            return layer
    return None


def check_layer_imports(
    edges: Sequence[ImportEdge], log: ExemptionLog
) -> list[CheckMessage]:
    """E101: a layer imports only the layers its row of the matrix allows."""
    messages: list[CheckMessage] = []
    seen: set[str] = set()
    for edge in edges:
        source = _layer(edge.module)
        target = _layer(edge.target)
        if source is None or target is None:
            continue
        if target in ALLOWED_IMPORTS[source]:
            continue
        ident = f"{edge.module} -> {edge.target}"
        if ident in seen:
            continue
        seen.add(ident)
        if log.allows("E101", ident):
            continue
        messages.append(
            pattern_error(
                "E101",
                ident,
                f"{edge.module} ({source}) imports {edge.target} "
                f"({target}), which the layer matrix forbids.",
                RULES["E101"],
            )
        )
    return messages


def check_api_utils_boundary(
    edges: Sequence[ImportEdge], log: ExemptionLog
) -> list[CheckMessage]:
    """E102: api surfaces import api.utils only through its package root."""
    messages: list[CheckMessage] = []
    seen: set[str] = set()
    for edge in edges:
        if not _in_package(edge.module, "clx.app.api"):
            continue
        if _in_package(edge.module, "clx.app.api.utils"):
            continue
        if not edge.target.startswith("clx.app.api.utils."):
            continue
        ident = f"{edge.module} -> {edge.target}"
        if ident in seen:
            continue
        seen.add(ident)
        if log.allows("E102", ident):
            continue
        messages.append(
            pattern_error(
                "E102",
                ident,
                f"{edge.module} imports {edge.target} directly; surfaces "
                f"import from the api.utils package root only.",
                RULES["E102"],
            )
        )
    return messages


def check_mcp_direction(
    edges: Sequence[ImportEdge], log: ExemptionLog
) -> list[CheckMessage]:
    """E103: nothing in clx.app imports clx.mcp."""
    messages: list[CheckMessage] = []
    seen: set[str] = set()
    for edge in edges:
        if not _in_package(edge.module, "clx.app"):
            continue
        if not _in_package(edge.target, "clx.mcp"):
            continue
        ident = f"{edge.module} -> {edge.target}"
        if ident in seen:
            continue
        seen.add(ident)
        if log.allows("E103", ident):
            continue
        messages.append(
            pattern_error(
                "E103",
                ident,
                f"{edge.module} imports {edge.target}; deleting clx/mcp "
                f"must remove the feature completely.",
                RULES["E103"],
            )
        )
    return messages


def check_app_modules_are_declared(
    modules: Mapping[str, ModuleInfo], log: ExemptionLog
) -> list[CheckMessage]:
    """E105: every top-level module of clx.app is declared architecture."""
    messages: list[CheckMessage] = []
    seen: set[str] = set()
    for name in modules:
        if not name.startswith("clx.app."):
            continue
        stem = name.split(".")[2]
        if stem in DECLARED_APP_MODULES or stem in seen:
            continue
        seen.add(stem)
        if log.allows("E105", stem):
            continue
        messages.append(
            pattern_error(
                "E105",
                stem,
                f"clx/app/{stem} is not a declared piece of the "
                f"architecture; add it to DECLARED_APP_MODULES and the "
                f"layer tables, and write its ground rules into CLAUDE.md.",
                RULES["E105"],
            )
        )
    return messages


def check_lazy_task_imports(
    edges: Sequence[ImportEdge], log: ExemptionLog
) -> list[CheckMessage]:
    """E104: services import the tasks layer inside function bodies only."""
    messages: list[CheckMessage] = []
    seen: set[str] = set()
    for edge in edges:
        if not edge.module_level:
            continue
        if _layer(edge.module) != "services":
            continue
        if _layer(edge.target) != "tasks":
            continue
        ident = f"{edge.module} -> {edge.target}"
        if ident in seen:
            continue
        seen.add(ident)
        if log.allows("E104", ident):
            continue
        messages.append(
            pattern_error(
                "E104",
                ident,
                f"{edge.module} imports {edge.target} at module level; "
                f"import it inside the function that queues it.",
                RULES["E104"],
            )
        )
    return messages
