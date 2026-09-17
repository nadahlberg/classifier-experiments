import ast
from collections.abc import Iterator, Mapping

from django.core.checks import CheckMessage

from clx.app.checks.base import ExemptionLog, pattern_error
from clx.app.selectors.codebase import ModuleInfo, _in_package

CACHE_METHODS = {
    "get",
    "set",
    "add",
    "touch",
    "delete",
    "get_many",
    "set_many",
    "delete_many",
    "get_or_set",
    "incr",
    "decr",
}

WRITE_METHODS = {
    "save",
    "create",
    "bulk_create",
    "bulk_update",
    "get_or_create",
    "update_or_create",
}

QUERYSET_WRITE_METHODS = {"update", "delete"}

READ_LAYERS = (
    "clx.app.selectors",
    "clx.app.api",
    "clx.app.views",
    "clx.app.tasks",
    "clx.app.management",
    "clx.app.templatetags",
    "clx.mcp.tools",
)

RULES = {
    "E601": (
        "Every cache key is a constant in app/cache.py — nothing passes a "
        "literal string to cache.get/cache.set."
    ),
    "E602": (
        "Services trigger tasks with transaction.on_commit(lambda: "
        "task.delay(...)), never before the write commits."
    ),
    "E603": (
        "signals.py holds signal handlers, connected in AppConfig.ready() "
        "— never mid-module elsewhere, where a connection fires for rows "
        "that may roll back."
    ),
    "E604": (
        "Business logic lives in services — anything that writes/mutates. "
        "Interfaces and selectors fetch; they never write."
    ),
    "E605": (
        "Wrap multi-write operations in @transaction.atomic — in the "
        "service, where the writes are."
    ),
    "E606": (
        "Call full_clean() inside the service, right before save() — "
        "constraints hold only on the paths that run them."
    ),
}


def _checked_modules(
    modules: Mapping[str, ModuleInfo],
) -> Iterator[tuple[str, ModuleInfo]]:
    """The modules the call checks scan: everything except the tests."""
    for name, info in modules.items():
        if _in_package(name, "clx.app.tests"):
            continue
        yield name, info


def _parents(tree: ast.Module) -> dict[int, ast.AST]:
    """Each node's parent, for walking upward from a call site."""
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def check_cache_key_literals(
    modules: Mapping[str, ModuleInfo], log: ExemptionLog
) -> list[CheckMessage]:
    """E601: cache calls take constants from cache.py, never literals."""
    messages: list[CheckMessage] = []
    for name, info in _checked_modules(modules):
        for node in ast.walk(info.tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in CACHE_METHODS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "cache"
                and node.args
                and isinstance(node.args[0], ast.Constant | ast.JoinedStr)
            ):
                continue
            ident = f"{name}:{node.lineno}"
            if log.allows("E601", ident):
                continue
            messages.append(
                pattern_error(
                    "E601",
                    ident,
                    f"{name}:{node.lineno} passes a literal key to "
                    f"cache.{node.func.attr}; name it in app/cache.py.",
                    RULES["E601"],
                )
            )
    return messages


def _inside_on_commit(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    """Whether a call sits inside a callable handed to on_commit."""
    child: ast.AST = node
    while id(child) in parents:
        parent = parents[id(child)]
        if isinstance(parent, ast.Call) and isinstance(
            child, ast.Lambda | ast.Name | ast.Attribute
        ):
            func = ast.unparse(parent.func)
            if func in ("transaction.on_commit", "on_commit"):
                return True
        child = parent
    return False


def check_tasks_queue_on_commit(
    modules: Mapping[str, ModuleInfo], log: ExemptionLog
) -> list[CheckMessage]:
    """E602: .delay()/.apply_async() run only inside on_commit callables."""
    messages: list[CheckMessage] = []
    for name, info in _checked_modules(modules):
        if _in_package(name, "clx.app.tasks"):
            continue
        parents = _parents(info.tree)
        for node in ast.walk(info.tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("delay", "apply_async")
            ):
                continue
            if _inside_on_commit(node, parents):
                continue
            ident = f"{name}:{node.lineno}"
            if log.allows("E602", ident):
                continue
            messages.append(
                pattern_error(
                    "E602",
                    ident,
                    f"{name}:{node.lineno} queues a task outside "
                    f"transaction.on_commit.",
                    RULES["E602"],
                )
            )
    return messages


def check_signals_connect_in_ready(
    modules: Mapping[str, ModuleInfo], log: ExemptionLog
) -> list[CheckMessage]:
    """E603: signal connections happen in apps.py or signals.py only."""
    allowed = {"clx.app.apps", "clx.app.signals"}
    messages: list[CheckMessage] = []
    for name, info in _checked_modules(modules):
        if name in allowed:
            continue
        for node in ast.walk(info.tree):
            if not isinstance(node, ast.Call | ast.FunctionDef):
                continue
            connect = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"
            )
            receiver = isinstance(node, ast.FunctionDef) and any(
                "receiver" in ast.unparse(item) for item in node.decorator_list
            )
            if not connect and not receiver:
                continue
            ident = f"{name}:{node.lineno}"
            if log.allows("E603", ident):
                continue
            messages.append(
                pattern_error(
                    "E603",
                    ident,
                    f"{name}:{node.lineno} connects a signal outside "
                    f"signals.py / AppConfig.ready().",
                    RULES["E603"],
                )
            )
    return messages


def check_writes_live_in_services(
    modules: Mapping[str, ModuleInfo], log: ExemptionLog
) -> list[CheckMessage]:
    """E604: model writes happen in services, never in read layers."""
    messages: list[CheckMessage] = []
    for name, info in _checked_modules(modules):
        if not any(_in_package(name, layer) for layer in READ_LAYERS):
            continue
        for node in ast.walk(info.tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
            ):
                continue
            attr = node.func.attr
            receiver = ast.unparse(node.func.value)
            is_write = attr in WRITE_METHODS and receiver != "cache"
            is_queryset_write = (
                attr in QUERYSET_WRITE_METHODS and ".objects" in receiver
            )
            if not is_write and not is_queryset_write:
                continue
            ident = f"{name}:{node.lineno}"
            if log.allows("E604", ident):
                continue
            messages.append(
                pattern_error(
                    "E604",
                    ident,
                    f"{name}:{node.lineno} calls .{attr}() in a read "
                    f"layer; the write belongs in a service.",
                    RULES["E604"],
                )
            )
    return messages


def check_full_clean_before_save(
    modules: Mapping[str, ModuleInfo], log: ExemptionLog
) -> list[CheckMessage]:
    """E606: in services, x.save() has an earlier x.full_clean() beside it."""
    messages: list[CheckMessage] = []
    for name, info in _checked_modules(modules):
        if not _in_package(name, "clx.app.services"):
            continue
        for fname, function in info.functions.items():
            cleaned: dict[str, int] = {}
            saves: list[tuple[str, int]] = []
            for node in ast.walk(function):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                ):
                    continue
                receiver = node.func.value.id
                if node.func.attr == "full_clean":
                    cleaned.setdefault(receiver, node.lineno)
                elif node.func.attr == "save" and not node.args:
                    saves.append((receiver, node.lineno))
            for receiver, lineno in saves:
                if cleaned.get(receiver, lineno) < lineno:
                    continue
                ident = f"{name}.{fname}"
                if log.allows("E606", ident):
                    continue
                if any(m.obj == ident for m in messages):
                    continue
                messages.append(
                    pattern_error(
                        "E606",
                        ident,
                        f"{name}:{lineno} saves {receiver} without an "
                        f"earlier {receiver}.full_clean().",
                        RULES["E606"],
                    )
                )
    return messages


def check_atomic_lives_in_services(
    modules: Mapping[str, ModuleInfo], log: ExemptionLog
) -> list[CheckMessage]:
    """E605: transaction.atomic appears in services only."""
    messages: list[CheckMessage] = []
    for name, info in _checked_modules(modules):
        if _in_package(name, "clx.app.services"):
            continue
        for node in ast.walk(info.tree):
            if not isinstance(
                node, ast.FunctionDef | ast.AsyncFunctionDef | ast.With
            ):
                continue
            texts: list[str]
            if isinstance(node, ast.With):
                texts = [ast.unparse(item.context_expr) for item in node.items]
            else:
                texts = [ast.unparse(item) for item in node.decorator_list]
            if not any(
                text == "atomic" or text.startswith("transaction.atomic")
                for text in texts
            ):
                continue
            ident = f"{name}:{node.lineno}"
            if log.allows("E605", ident):
                continue
            messages.append(
                pattern_error(
                    "E605",
                    ident,
                    f"{name}:{node.lineno} opens transaction.atomic "
                    f"outside the service layer.",
                    RULES["E605"],
                )
            )
    return messages
