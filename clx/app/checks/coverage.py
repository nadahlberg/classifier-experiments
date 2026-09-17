from collections.abc import Sequence

from django.core.checks import CheckMessage

from clx.app.checks.base import ExemptionLog, pattern_error
from clx.app.selectors.codebase import McpToolFact, RouteFact

RULES = {
    "E701": (
        "API endpoints declare their auth with @api_auth — a route "
        "without it is public by accident, not by decision."
    ),
    "E702": (
        'HTML views guard with @permission_required("app.manage_admin") '
        "— hiding the link is not a substitute for guarding the "
        "destination."
    ),
    "E703": (
        "Every tool sets every field of ToolAnnotations, explicitly, even "
        "the ones that only matter when readOnlyHint is false."
    ),
}


def check_api_routes_declare_auth(
    routes: Sequence[RouteFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E701: every route served from api/ carries the api_auth stash."""
    messages: list[CheckMessage] = []
    for fact in routes:
        if not fact.module.startswith("clx.app.api."):
            continue
        if fact.has_api_auth:
            continue
        ident = f"{fact.module}.{fact.qualname}"
        if log.allows("E701", ident):
            continue
        messages.append(
            pattern_error(
                "E701",
                ident,
                f"{ident} serves {fact.route!r} without @api_auth.",
                RULES["E701"],
            )
        )
    return messages


def check_admin_views_require_permission(
    routes: Sequence[RouteFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E702: every admin/ view carries @permission_required."""
    messages: list[CheckMessage] = []
    for fact in routes:
        if not fact.module.startswith("clx.app.views."):
            continue
        if not fact.route.startswith("admin/"):
            continue
        if any(
            decorator.startswith("@permission_required")
            for decorator in fact.decorators
        ):
            continue
        ident = f"{fact.module}.{fact.qualname}"
        if log.allows("E702", ident):
            continue
        messages.append(
            pattern_error(
                "E702",
                ident,
                f"{ident} serves {fact.route!r} without @permission_required.",
                RULES["E702"],
            )
        )
    return messages


def check_mcp_tools_complete_their_annotations(
    tools: Sequence[McpToolFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E703: every MCP tool sets every ToolAnnotations field."""
    messages: list[CheckMessage] = []
    for fact in tools:
        if not fact.missing_annotations:
            continue
        if log.allows("E703", fact.name):
            continue
        messages.append(
            pattern_error(
                "E703",
                fact.name,
                f"MCP tool {fact.name} leaves ToolAnnotations fields "
                f"unset: {', '.join(fact.missing_annotations)}.",
                RULES["E703"],
            )
        )
    return messages
