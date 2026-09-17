from collections.abc import Sequence

from django.core.checks import CheckMessage

from clx.app.checks.base import ExemptionLog, pattern_error
from clx.app.scripts import scripts_directives
from clx.app.selectors.codebase import TemplateFact

RULES = {
    "E501": (
        "Directive expressions are a grammar, not JavaScript — and "
        "illegal expressions fail silently to empty, so nothing crashes "
        "when one slips in."
    ),
    "E502": (
        "x-model is illegal (its setter compiles to an assignment); use "
        ":value + @input pairs instead."
    ),
    "E503": (
        "Alpine.data is lazy — init() runs only where an element declares "
        'x-data="name" — so a name no script block registers is a '
        "component that silently never starts."
    ),
    "E504": (
        "A style binding writes the style attribute, which style-src "
        "'self' blocks; set the property from the component's own "
        "JavaScript instead."
    ),
}

STYLE_DIRECTIVES = (":style", "x-bind:style")


def check_directive_grammar(
    templates: Sequence[TemplateFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E501/E502: every directive expression is legal under the CSP build."""
    messages: list[CheckMessage] = []
    for fact in templates:
        for directive in scripts_directives(fact.text):
            if directive.error is None:
                continue
            check_id = (
                "E502" if directive.name.startswith("x-model") else "E501"
            )
            ident = f"{fact.name}:{directive.line}"
            if log.allows(check_id, ident):
                continue
            messages.append(
                pattern_error(
                    check_id,
                    ident,
                    f"{fact.name}:{directive.line} {directive.name}="
                    f'"{directive.expression}" — {directive.error}.',
                    RULES[check_id],
                )
            )
    return messages


def check_data_names_are_registered(
    templates: Sequence[TemplateFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E503: every x-data name has an Alpine registration in some template."""
    registered = {name for fact in templates for name in fact.registrations}
    messages: list[CheckMessage] = []
    for fact in templates:
        for directive in scripts_directives(fact.text):
            if directive.name != "x-data" or directive.error is not None:
                continue
            if directive.expression in registered:
                continue
            ident = f"{fact.name}:{directive.expression}"
            if log.allows("E503", ident):
                continue
            messages.append(
                pattern_error(
                    "E503",
                    ident,
                    f"{fact.name} declares x-data="
                    f'"{directive.expression}" but no script block '
                    f"registers that name.",
                    RULES["E503"],
                )
            )
    return messages


def check_no_style_bindings(
    templates: Sequence[TemplateFact], log: ExemptionLog
) -> list[CheckMessage]:
    """E504: no directive binds the style attribute."""
    messages: list[CheckMessage] = []
    for fact in templates:
        for directive in scripts_directives(fact.text):
            if directive.name.split(".", 1)[0] not in STYLE_DIRECTIVES:
                continue
            ident = f"{fact.name}:{directive.line}"
            if log.allows("E504", ident):
                continue
            messages.append(
                pattern_error(
                    "E504",
                    ident,
                    f"{fact.name}:{directive.line} binds "
                    f"{directive.name}; Alpine writes that through the "
                    f"style attribute, which the CSP blocks.",
                    RULES["E504"],
                )
            )
    return messages
