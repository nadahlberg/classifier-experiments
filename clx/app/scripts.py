import re
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import cast

from django.conf import settings

from clx.app.exceptions import ApplicationError

SCRIPT_BLOCK = re.compile(r"{%\s*script\s*%}(.*?){%\s*endscript\s*%}", re.S)
SCRIPT_TAG = re.compile(r"\A\s*<script[^>]*>(.*)</script>\s*\Z", re.S)
REGISTRATION = re.compile(
    r"""Alpine\.(?:data|store)\(\s*["']([^"']+)["']\s*,"""
)
DECLARATION = re.compile(
    r"^(?:const|let|var|async\s+function|function|class)\s+"
    r"([A-Za-z_$][\w$]*)",
    re.M,
)

DIRECTIVE = re.compile(r'\s((?:x-|@|:)[\w:.@\-]*)="([^"]*)"')
PATH_EXPRESSION = re.compile(r"\$?[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*\Z")
FOR_EXPRESSION = re.compile(
    r"(?:[A-Za-z_][\w$]*|\(\s*[A-Za-z_][\w$]*\s*"
    r"(?:,\s*[A-Za-z_][\w$]*\s*)?\))\s+in\s+"
    r"\$?[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*\Z"
)
UNCHECKED_DIRECTIVES = ("x-transition", "x-cloak", "x-ref", "x-teleport")


@dataclass(frozen=True)
class Directive:
    name: str
    expression: str
    line: int
    error: str | None


def _directive_error(name: str, expression: str) -> str | None:
    """Why an expression is outside the CSP build's grammar, or None."""
    base = name.split(".", 1)[0]
    if base.startswith(UNCHECKED_DIRECTIVES):
        return None
    if base.startswith("x-model"):
        return "x-model compiles to an assignment; use :value + @input"
    if base == "x-data":
        if re.fullmatch(r"[A-Za-z_][\w$]*", expression):
            return None
        return "x-data takes a registered component name"
    if base == "x-for":
        if FOR_EXPRESSION.fullmatch(expression.strip()):
            return None
        return "x-for takes `item in path`, nothing more"
    if PATH_EXPRESSION.fullmatch(expression.strip()):
        return None
    return (
        "not a property path or method reference; operators, arguments "
        "and assignments fail silently to empty under the CSP build"
    )


def scripts_directives(source: str) -> list[Directive]:
    """Every Alpine directive in a template, each with its grammar verdict."""
    found = []
    for match in DIRECTIVE.finditer(source):
        name, expression = match.group(1), match.group(2)
        found.append(
            Directive(
                name=name,
                expression=expression,
                line=source.count("\n", 0, match.start()) + 1,
                error=_directive_error(name, expression),
            )
        )
    return found


def scripts_dirs() -> list[Path]:
    """The template directories the bundle is compiled from."""
    dirs = cast("list[str]", settings.TEMPLATES[0]["DIRS"])
    return [Path(directory) for directory in dirs]


def scripts_bodies(source: str, *, origin: str) -> list[str]:
    """Extract the JavaScript from every script block in a template."""
    bodies = []
    for block in SCRIPT_BLOCK.findall(source):
        if "{%" in block or "{{" in block:
            raise ApplicationError(
                f"{origin}: {{% script %}} takes literal JavaScript. Pass "
                f"template values as data attributes and read them in init()."
            )
        match = SCRIPT_TAG.match(block)
        if match is None:
            raise ApplicationError(
                f"{origin}: {{% script %}} content must be wrapped in "
                f"<script> tags."
            )
        bodies.append(dedent(match.group(1)).strip())
    return bodies
