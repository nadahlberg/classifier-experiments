import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from django.conf import settings
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from clx.app.scripts import (
    REGISTRATION,
    scripts_bodies,
    scripts_dirs,
)

_Def = ast.FunctionDef | ast.AsyncFunctionDef

REPO_ROOT = Path(settings.BASE_DIR).resolve().parent
COTTON_BUILTIN_TAGS = {"vars", "slot", "component"}

TAG_USE = re.compile(r"<c-([A-Za-z0-9.-]+)")
CVARS = re.compile(r"<c-vars\s+([^>]*?)/?>", re.S)
EXTENDS = re.compile(r"{%\s*extends\s+[\"']([^\"']+)[\"']")


@dataclass
class _TemplateInfo:
    text: str
    bodies: list[str]


@dataclass
class ModuleInfo:
    path: Path
    rel: str
    source: str
    lines: list[str]
    tree: ast.Module
    functions: dict[str, _Def]
    classes: dict[str, ast.ClassDef]


@dataclass(frozen=True)
class ImportEdge:
    module: str
    target: str
    symbol: str | None
    module_level: bool


@dataclass(frozen=True)
class RouteFact:
    name: str | None
    route: str
    module: str
    qualname: str
    has_api_auth: bool
    decorators: tuple[str, ...]
    is_redirect: bool
    template_name: str | None


@dataclass(frozen=True)
class PatternListFact:
    name: str
    prefix: str | None
    routes: tuple[str, ...]
    names: tuple[str | None, ...]
    modules: tuple[str, ...]


@dataclass(frozen=True)
class TemplateFact:
    name: str
    root: str
    path: str
    text: str
    extends: str | None
    used_tags: tuple[str, ...]
    registrations: tuple[str, ...]
    has_cvars: bool


@dataclass(frozen=True)
class McpToolFact:
    name: str
    missing_annotations: tuple[str, ...]


@dataclass(frozen=True)
class CodebaseFacts:
    modules: dict[str, ModuleInfo]
    import_edges: tuple[ImportEdge, ...]
    routes: tuple[RouteFact, ...]
    pattern_lists: tuple[PatternListFact, ...]
    templates: tuple[TemplateFact, ...]
    rendered: frozenset[str]
    template_strings: frozenset[str]
    mcp_tools: tuple[McpToolFact, ...]


def _in_package(module_name: str, package: str) -> bool:
    """Whether a module is the given package or lives inside it."""
    return module_name == package or module_name.startswith(package + ".")


def _rel(path: Path | str) -> str:
    """The repo-relative posix form of a path, absolute when outside."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _decorators(node: _Def | ast.ClassDef) -> list[str]:
    """A definition's decorators as written in the source."""
    return [f"@{ast.unparse(item)}" for item in node.decorator_list]


def _walk_patterns(
    patterns: list[Any], prefix: str, namespace: str
) -> Iterator[tuple[str, str | None, Any]]:
    """Yield every (route, url name, callback) under the given patterns."""
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            inner = ":".join(
                part for part in (namespace, pattern.namespace or "") if part
            )
            yield from _walk_patterns(
                pattern.url_patterns,
                prefix + str(pattern.pattern),
                inner,
            )
        elif isinstance(pattern, URLPattern):
            name = ":".join(
                part for part in (namespace, pattern.name or "") if part
            )
            yield (
                prefix + str(pattern.pattern),
                name or None,
                pattern.callback,
            )


def _used_tags(text: str) -> list[str]:
    """The cotton tags a template's markup references, in order."""
    return [
        f"c-{tag}"
        for tag in dict.fromkeys(TAG_USE.findall(text))
        if tag not in COTTON_BUILTIN_TAGS
    ]


class _Extractor:
    """One parse of the codebase, feeding the pattern checks' fact tables."""

    def __init__(self) -> None:
        self._modules: dict[str, ModuleInfo] = {}
        self._templates: dict[str, _TemplateInfo] = {}

    def module(self, file: str | None) -> ModuleInfo:
        """The parsed source of a python module, cached per build."""
        if file is None:
            raise ValueError("module has no source file")
        key = str(Path(file).resolve())
        if key not in self._modules:
            path = Path(key)
            source = path.read_text()
            tree = ast.parse(source)
            functions: dict[str, _Def] = {}
            classes: dict[str, ast.ClassDef] = {}
            for node in tree.body:
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    functions[node.name] = node
                elif isinstance(node, ast.ClassDef):
                    classes[node.name] = node
            self._modules[key] = ModuleInfo(
                path=path,
                rel=_rel(path),
                source=source,
                lines=source.splitlines(),
                tree=tree,
                functions=functions,
                classes=classes,
            )
        return self._modules[key]

    def template(self, path: Path) -> _TemplateInfo:
        """The text and script bodies of a template, cached per build."""
        key = str(path.resolve())
        if key not in self._templates:
            text = path.read_text()
            self._templates[key] = _TemplateInfo(
                text=text,
                bodies=scripts_bodies(text, origin=_rel(path)),
            )
        return self._templates[key]

    def app_modules(self) -> dict[str, ModuleInfo]:
        """Every first-party module by dotted name, migrations excluded."""
        modules: dict[str, ModuleInfo] = {}
        for path in sorted((REPO_ROOT / "clx").rglob("*.py")):
            parts = path.relative_to(REPO_ROOT).parts
            if "migrations" in parts or "__pycache__" in parts:
                continue
            dotted = ".".join(parts)[: -len(".py")]
            if dotted.endswith(".__init__"):
                dotted = dotted[: -len(".__init__")]
            modules[dotted] = self.module(str(path))
        return modules

    def import_edges(self) -> tuple[ImportEdge, ...]:
        """Every import in every first-party module, with its position."""
        edges: list[ImportEdge] = []
        for name, info in self.app_modules().items():
            in_function: set[int] = set()
            for fn in ast.walk(info.tree):
                if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                    for sub in ast.walk(fn):
                        if sub is not fn:
                            in_function.add(id(sub))
            is_package = info.path.name == "__init__.py"
            for node in ast.walk(info.tree):
                level = id(node) not in in_function
                if isinstance(node, ast.Import):
                    edges.extend(
                        ImportEdge(name, alias.name, None, level)
                        for alias in node.names
                    )
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        parts = name.split(".")
                        if not is_package:
                            parts = parts[:-1]
                        parts = parts[: len(parts) - (node.level - 1)]
                        base = ".".join(parts)
                        target = (
                            f"{base}.{node.module}" if node.module else base
                        )
                    else:
                        target = node.module or ""
                    edges.extend(
                        ImportEdge(name, target, alias.name, level)
                        for alias in node.names
                    )
        return tuple(edges)

    def routes_with_callbacks(self) -> list[tuple[RouteFact, Any]]:
        """Every resolver route as a fact, paired with its live callback."""
        found = []
        patterns = get_resolver().url_patterns
        for route, url_name, callback in _walk_patterns(patterns, "", ""):
            module_name = getattr(callback, "__module__", "")
            decorators: tuple[str, ...] = ()
            if module_name.startswith(("clx.app.api.", "clx.app.views.")):
                info = self.module(import_module(module_name).__file__)
                node = info.functions.get(callback.__name__)
                if node is not None:
                    decorators = tuple(_decorators(node))
            view_class = getattr(callback, "view_class", None)
            initkwargs = getattr(callback, "view_initkwargs", None) or {}
            template_name = initkwargs.get("template_name")
            fact = RouteFact(
                name=url_name,
                route=route,
                module=module_name,
                qualname=getattr(callback, "__name__", ""),
                has_api_auth=getattr(callback, "api_auth", None) is not None,
                decorators=decorators,
                is_redirect=getattr(view_class, "__name__", "")
                == "RedirectView",
                template_name=(
                    template_name if isinstance(template_name, str) else None
                ),
            )
            found.append((fact, callback))
        return found

    def pattern_lists(self) -> tuple[PatternListFact, ...]:
        """Every surface pattern list urls.py declares, with its prefix."""
        urls = import_module("clx.app.urls")
        prefixes: dict[int, str] = {}
        for entry in urls.urlpatterns:
            if isinstance(entry, URLResolver):
                prefixes[id(entry.url_patterns)] = str(entry.pattern)
        facts = []
        for name, value in vars(urls).items():
            if not name.endswith(("_api_patterns", "_view_patterns")):
                continue
            if not isinstance(value, list):
                continue
            local = [p for p in value if isinstance(p, URLPattern)]
            facts.append(
                PatternListFact(
                    name=name,
                    prefix=prefixes.get(id(value)),
                    routes=tuple(str(p.pattern) for p in local),
                    names=tuple(p.name for p in local),
                    modules=tuple(
                        getattr(p.callback, "__module__", "") for p in local
                    ),
                )
            )
        return tuple(facts)

    def template_facts(self) -> tuple[TemplateFact, ...]:
        """Every template under both roots, as a fact."""
        facts = []
        for directory in scripts_dirs():
            for path in sorted(directory.rglob("*")):
                if not path.is_file():
                    continue
                info = self.template(path)
                extends = EXTENDS.search(info.text)
                registrations = [
                    match.group(1)
                    for body in info.bodies
                    for match in REGISTRATION.finditer(body)
                ]
                facts.append(
                    TemplateFact(
                        name=path.relative_to(directory).as_posix(),
                        root=directory.name,
                        path=_rel(path),
                        text=info.text,
                        extends=extends.group(1) if extends else None,
                        used_tags=tuple(_used_tags(info.text)),
                        registrations=tuple(registrations),
                        has_cvars=CVARS.search(info.text) is not None,
                    )
                )
        return tuple(facts)

    def rendered(self) -> frozenset[str]:
        """Every template name a view renders or a route serves."""
        names: set[str] = set()
        for info in self.app_modules().values():
            for node in ast.walk(info.tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "render"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                ):
                    names.add(node.args[1].value)
        for fact, _ in self.routes_with_callbacks():
            if fact.template_name:
                names.add(fact.template_name)
        return frozenset(names)

    def template_strings(self) -> frozenset[str]:
        """Every template name a Python string literal carries."""
        names: set[str] = set()
        for info in self.app_modules().values():
            for node in ast.walk(info.tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.endswith(".html")
                ):
                    names.add(node.value)
        return frozenset(names)

    def mcp_tool_facts(self) -> tuple[McpToolFact, ...]:
        """Every registered MCP tool with its unset annotation fields."""
        try:
            import_module("clx.mcp.tools")
        except ModuleNotFoundError:
            return ()
        from mcp.types import ToolAnnotations

        base = import_module("clx.mcp.tools.base")
        facts = []
        for tool in base.TOOLS.values():
            annotations = tool.annotations
            if annotations is None:
                missing = tuple(sorted(ToolAnnotations.model_fields))
            else:
                missing = tuple(
                    sorted(
                        set(type(annotations).model_fields)
                        - annotations.model_fields_set
                    )
                )
            facts.append(
                McpToolFact(name=tool.name, missing_annotations=missing)
            )
        return tuple(facts)

    def facts(self) -> CodebaseFacts:
        """The fact tables the pattern checks assert over."""
        return CodebaseFacts(
            modules=self.app_modules(),
            import_edges=self.import_edges(),
            routes=tuple(f for f, _ in self.routes_with_callbacks()),
            pattern_lists=self.pattern_lists(),
            templates=self.template_facts(),
            rendered=self.rendered(),
            template_strings=self.template_strings(),
            mcp_tools=self.mcp_tool_facts(),
        )


def codebase_facts() -> CodebaseFacts:
    """The fact tables the pattern checks assert over, from one parse."""
    return _Extractor().facts()
