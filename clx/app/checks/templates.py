from collections.abc import Sequence
from pathlib import PurePosixPath

from django.core.checks import CheckMessage

from clx.app.checks.base import ExemptionLog, pattern_error
from clx.app.selectors.codebase import RouteFact, TemplateFact

RULES = {
    "E401": "Does a URL render it? -> templates/pages/.",
    "E402": (
        "Is it a frame several pages share? -> templates/layouts/ — a "
        "layout nothing extends is dead markup."
    ),
    "E403": (
        "Every reusable or extracted piece lives in cotton/ — a component "
        "nothing uses is dead markup."
    ),
    "E404": (
        "There are no partials. {% include %} is not used; everything is "
        "a cotton component."
    ),
    "E405": (
        "A surface with sub-pages is a folder — never a file beside a "
        "folder of the same name, so a surface's templates live in one "
        "place."
    ),
    "E406": (
        "A surface's bare route renders the folder's index.html. A "
        "surface whose bare route redirects to a sub-page has no index."
    ),
    "E407": (
        "Root-level components declare <c-vars> and take only, because a "
        "shared primitive should have an explicit interface."
    ),
}


def _tag(name: str) -> str:
    """The cotton tag a template under cotton/ answers to."""
    parts = PurePosixPath(name).with_suffix("").parts[1:]
    return "c-" + ".".join(part.replace("_", "-") for part in parts)


def check_pages_are_routed(
    templates: Sequence[TemplateFact],
    rendered: frozenset[str],
    log: ExemptionLog,
) -> list[CheckMessage]:
    """E401: every template under pages/ is rendered by some route."""
    messages: list[CheckMessage] = []
    for fact in templates:
        if fact.root != "templates":
            continue
        if not fact.name.startswith("pages/"):
            continue
        if fact.name in rendered:
            continue
        if log.allows("E401", fact.name):
            continue
        messages.append(
            pattern_error(
                "E401",
                fact.name,
                f"No route renders {fact.name}; a page nothing serves is "
                f"dead markup.",
                RULES["E401"],
            )
        )
    return messages


def check_layouts_are_extended(
    templates: Sequence[TemplateFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E402: every template under layouts/ is extended by something."""
    extended = {fact.extends for fact in templates if fact.extends}
    messages: list[CheckMessage] = []
    for fact in templates:
        if fact.root != "templates":
            continue
        if not fact.name.startswith("layouts/"):
            continue
        if fact.name in extended:
            continue
        if log.allows("E402", fact.name):
            continue
        messages.append(
            pattern_error(
                "E402",
                fact.name,
                f"Nothing extends {fact.name}.",
                RULES["E402"],
            )
        )
    return messages


def check_components_are_used(
    templates: Sequence[TemplateFact],
    template_strings: frozenset[str],
    log: ExemptionLog,
) -> list[CheckMessage]:
    """E403: every cotton component is used by a template or Python code."""
    used = {tag for fact in templates for tag in fact.used_tags}
    messages: list[CheckMessage] = []
    for fact in templates:
        if fact.root != "templates":
            continue
        if not fact.name.startswith("cotton/"):
            continue
        if _tag(fact.name) in used or fact.name in template_strings:
            continue
        if log.allows("E403", fact.name):
            continue
        messages.append(
            pattern_error(
                "E403",
                fact.name,
                f"No template uses <{_tag(fact.name)} />.",
                RULES["E403"],
            )
        )
    return messages


def check_no_includes(
    templates: Sequence[TemplateFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E404: no template uses the include tag."""
    messages: list[CheckMessage] = []
    for fact in templates:
        if "{% include" not in fact.text:
            continue
        if log.allows("E404", fact.name):
            continue
        messages.append(
            pattern_error(
                "E404",
                fact.name,
                f"{fact.name} uses {{% include %}}; extract a cotton "
                f"component instead.",
                RULES["E404"],
            )
        )
    return messages


def check_no_same_name_pairs(
    templates: Sequence[TemplateFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E405: no template file sits beside a folder of the same name."""
    directories = {
        str(parent)
        for fact in templates
        for parent in PurePosixPath(fact.name).parents
        if str(parent) != "."
    }
    messages: list[CheckMessage] = []
    for fact in templates:
        if fact.root != "templates":
            continue
        stem = str(PurePosixPath(fact.name).with_suffix(""))
        if stem not in directories:
            continue
        if log.allows("E405", fact.name):
            continue
        messages.append(
            pattern_error(
                "E405",
                fact.name,
                f"{fact.name} sits beside the folder {stem}/; the bare "
                f"route belongs at {stem}/index.html.",
                RULES["E405"],
            )
        )
    return messages


def check_surface_folders_have_an_index(
    templates: Sequence[TemplateFact],
    routes: Sequence[RouteFact],
    log: ExemptionLog,
) -> list[CheckMessage]:
    """E406: a pages/ folder has an index.html or a redirecting bare route."""
    names = {fact.name for fact in templates if fact.root == "templates"}
    folders = {
        PurePosixPath(fact.name).parts[1]
        for fact in templates
        if fact.root == "templates"
        and fact.name.startswith("pages/")
        and len(PurePosixPath(fact.name).parts) > 2
    }
    redirected = {fact.route for fact in routes if fact.is_redirect}
    messages: list[CheckMessage] = []
    for folder in sorted(folders):
        if f"pages/{folder}/index.html" in names:
            continue
        if f"{folder}/" in redirected:
            continue
        if log.allows("E406", folder):
            continue
        messages.append(
            pattern_error(
                "E406",
                folder,
                f"pages/{folder}/ has no index.html and its bare route "
                f"is not a redirect.",
                RULES["E406"],
            )
        )
    return messages


def check_root_components_declare_cvars(
    templates: Sequence[TemplateFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E407: root cotton primitives declare their interface with c-vars."""
    messages: list[CheckMessage] = []
    for fact in templates:
        if fact.root != "templates":
            continue
        parts = PurePosixPath(fact.name).parts
        if parts[0] != "cotton" or len(parts) != 2:
            continue
        if fact.has_cvars:
            continue
        if log.allows("E407", fact.name):
            continue
        messages.append(
            pattern_error(
                "E407",
                fact.name,
                f"{fact.name} is a root primitive with no <c-vars> "
                f"declaration.",
                RULES["E407"],
            )
        )
    return messages
