from collections.abc import Sequence

from django.core.checks import CheckMessage

from clx.app.checks.base import ExemptionLog, pattern_error
from clx.app.selectors.codebase import PatternListFact, RouteFact

RULES = {
    "E301": (
        "A surface has one name, used verbatim in three places: the "
        "interface module, its pattern list, and the URL prefix the list "
        "is included under."
    ),
    "E302": "URL names carry the same surface prefix.",
    "E303": (
        "Two routes reversing under one name shadow each other silently — "
        "every qualified URL name resolves to exactly one route."
    ),
    "E304": (
        "A prefix shared by every route in a list is applied where the "
        "list is included in urlpatterns, not repeated inside the list "
        "itself."
    ),
}


def _surface(list_name: str) -> tuple[str, str]:
    """A pattern list's surface name and its expected include prefix."""
    if list_name.endswith("_api_patterns"):
        surface = list_name.removesuffix("_api_patterns")
        return surface, f"api/{surface}/"
    surface = list_name.removesuffix("_view_patterns")
    return surface, f"{surface}/"


def check_surface_triads(
    pattern_lists: Sequence[PatternListFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E301: list name, include prefix, and interface module agree."""
    messages: list[CheckMessage] = []
    for fact in pattern_lists:
        if fact.prefix is None:
            continue
        surface, expected_prefix = _surface(fact.name)
        expected_module = (
            f"clx.app.api.{surface}"
            if fact.name.endswith("_api_patterns")
            else f"clx.app.views.{surface}"
        )
        problems = []
        if fact.prefix != expected_prefix:
            problems.append(
                f"included at {fact.prefix!r}, not {expected_prefix!r}"
            )
        strays = {
            module
            for module in fact.modules
            if module.startswith("clx.") and module != expected_module
        }
        if strays:
            problems.append(
                f"routes callbacks from {', '.join(sorted(strays))}, "
                f"not {expected_module}"
            )
        if not problems:
            continue
        if log.allows("E301", fact.name):
            continue
        messages.append(
            pattern_error(
                "E301",
                fact.name,
                f"{fact.name} breaks the surface triad: "
                f"{'; '.join(problems)}.",
                RULES["E301"],
            )
        )
    return messages


def check_url_name_prefixes(
    pattern_lists: Sequence[PatternListFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E302: names in a prefixed list carry the surface as their prefix."""
    messages: list[CheckMessage] = []
    for fact in pattern_lists:
        if fact.prefix is None:
            continue
        surface, _ = _surface(fact.name)
        for name in fact.names:
            if name is None:
                continue
            if name == surface or name.startswith(f"{surface}-"):
                continue
            if log.allows("E302", name):
                continue
            messages.append(
                pattern_error(
                    "E302",
                    name,
                    f"URL name {name!r} in {fact.name} does not carry the "
                    f"{surface!r} surface prefix.",
                    RULES["E302"],
                )
            )
    return messages


def check_url_name_uniqueness(
    routes: Sequence[RouteFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E303: no qualified URL name appears on two routes."""
    seen: dict[str, str] = {}
    messages: list[CheckMessage] = []
    for fact in routes:
        if fact.name is None:
            continue
        if fact.name not in seen:
            seen[fact.name] = fact.route
            continue
        if log.allows("E303", fact.name):
            continue
        messages.append(
            pattern_error(
                "E303",
                fact.name,
                f"URL name {fact.name!r} names both {seen[fact.name]!r} "
                f"and {fact.route!r}; reverse() resolves only one.",
                RULES["E303"],
            )
        )
    return messages


def check_prefixes_live_at_the_include(
    pattern_lists: Sequence[PatternListFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E304: no pattern list repeats its own surface in every route."""
    messages: list[CheckMessage] = []
    for fact in pattern_lists:
        if not fact.routes:
            continue
        surface, _ = _surface(fact.name)
        if any(route.split("/", 1)[0] != surface for route in fact.routes):
            continue
        if log.allows("E304", fact.name):
            continue
        messages.append(
            pattern_error(
                "E304",
                fact.name,
                f"Every route in {fact.name} starts with "
                f"{surface + '/'!r}; apply the prefix where the list is "
                f"included.",
                RULES["E304"],
            )
        )
    return messages
