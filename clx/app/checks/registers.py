import ast
from collections.abc import Mapping, Sequence

from django.core.checks import CheckMessage

from clx.app.checks.base import ExemptionLog, pattern_error
from clx.app.selectors.codebase import ModuleInfo

MACHINERY_STEMS = {"utils"}

RULES = {
    "E201": (
        "Services / selectors: <entity>_<action> — the module carries the "
        "domain, and every public function in it carries the domain's "
        "prefix."
    ),
    "E202": (
        "Tasks live in tasks/, grouped by domain, and a task is named "
        "<entity>_<action>_task."
    ),
    "E203": (
        "Mapping and builder are two halves of one contract, which is why "
        "they live in the same file — every *_index name builder has its "
        "{BASE}_MAPPING and {base}_document beside it."
    ),
    "E204": (
        "Group conceptually related models into separate files inside "
        "models/ and re-export them from models/__init__.py so they "
        "import as from clx.app.models import User."
    ),
    "E205": (
        "Services take keyword-only arguments (unless zero or one "
        "argument). A selector follows the same rules as a service."
    ),
}


def _domain_modules(
    modules: Mapping[str, ModuleInfo], package: str
) -> dict[str, ModuleInfo]:
    """The package's direct domain modules by stem, machinery excluded."""
    found = {}
    for name, info in modules.items():
        head, _, stem = name.rpartition(".")
        if head != package or stem.startswith("_"):
            continue
        if stem in MACHINERY_STEMS:
            continue
        found[stem] = info
    return found


def check_domain_prefixes(
    modules: Mapping[str, ModuleInfo], log: ExemptionLog
) -> list[CheckMessage]:
    """E201: public service and selector functions carry their module stem."""
    messages: list[CheckMessage] = []
    for package in ("clx.app.services", "clx.app.selectors"):
        for stem, info in _domain_modules(modules, package).items():
            for fname in info.functions:
                if fname.startswith("_"):
                    continue
                if fname == stem or fname.startswith(f"{stem}_"):
                    continue
                ident = f"{package}.{stem}.{fname}"
                if log.allows("E201", ident):
                    continue
                messages.append(
                    pattern_error(
                        "E201",
                        ident,
                        f"{fname} in {package}.{stem} does not carry the "
                        f"{stem}_ domain prefix.",
                        RULES["E201"],
                    )
                )
    return messages


def check_task_names(
    modules: Mapping[str, ModuleInfo], log: ExemptionLog
) -> list[CheckMessage]:
    """E202: tasks carry their domain prefix and the _task suffix."""
    messages: list[CheckMessage] = []
    for stem, info in _domain_modules(modules, "clx.app.tasks").items():
        for fname in info.functions:
            if fname.startswith("_"):
                continue
            if fname.endswith("_task") and fname.startswith(f"{stem}_"):
                continue
            ident = f"clx.app.tasks.{stem}.{fname}"
            if log.allows("E202", ident):
                continue
            messages.append(
                pattern_error(
                    "E202",
                    ident,
                    f"{fname} in tasks/{stem}.py must be named "
                    f"{stem}_<action>_task.",
                    RULES["E202"],
                )
            )
    return messages


def check_model_reexports(
    model_names: Sequence[str],
    exported: frozenset[str],
    log: ExemptionLog,
) -> list[CheckMessage]:
    """E204: every concrete model is re-exported from models/__init__.py."""
    messages: list[CheckMessage] = []
    for name in model_names:
        if name in exported:
            continue
        if log.allows("E204", name):
            continue
        messages.append(
            pattern_error(
                "E204",
                name,
                f"{name} is not re-exported from models/__init__.py.",
                RULES["E204"],
            )
        )
    return messages


def check_keyword_only_arguments(
    modules: Mapping[str, ModuleInfo], log: ExemptionLog
) -> list[CheckMessage]:
    """E205: public service and selector functions take at most one positional."""
    messages: list[CheckMessage] = []
    for package in ("clx.app.services", "clx.app.selectors"):
        for stem, info in _domain_modules(modules, package).items():
            for fname, node in info.functions.items():
                if fname.startswith("_"):
                    continue
                positional = len(node.args.posonlyargs) + len(node.args.args)
                if positional <= 1:
                    continue
                ident = f"{package}.{stem}.{fname}"
                if log.allows("E205", ident):
                    continue
                messages.append(
                    pattern_error(
                        "E205",
                        ident,
                        f"{fname} in {package}.{stem} takes {positional} "
                        f"positional arguments; make them keyword-only.",
                        RULES["E205"],
                    )
                )
    return messages


def check_search_contract(
    info: ModuleInfo, log: ExemptionLog
) -> list[CheckMessage]:
    """E203: every *_index in search.py has its mapping and builder."""
    assigns: set[str] = set()
    for node in info.tree.body:
        if isinstance(node, ast.Assign):
            assigns.update(
                t.id for t in node.targets if isinstance(t, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(
            node.target, ast.Name
        ):
            assigns.add(node.target.id)
    messages: list[CheckMessage] = []
    for fname in info.functions:
        if fname.startswith("_") or not fname.endswith("_index"):
            continue
        base = fname.removesuffix("_index")
        missing = []
        if f"{base.upper()}_MAPPING" not in assigns:
            missing.append(f"{base.upper()}_MAPPING")
        if f"{base}_document" not in info.functions:
            missing.append(f"{base}_document")
        if not missing:
            continue
        if log.allows("E203", fname):
            continue
        messages.append(
            pattern_error(
                "E203",
                fname,
                f"{fname} has no {' or '.join(missing)} beside it; the "
                f"index contract is incomplete.",
                RULES["E203"],
            )
        )
    return messages
