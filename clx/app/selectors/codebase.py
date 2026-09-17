import ast
import json
import re
import weakref
from collections.abc import Iterator
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules
from types import ModuleType
from typing import Any, cast

from django.apps import apps
from django.conf import settings
from django.core.checks.registry import registry as check_registry
from django.db.models import Field, Model
from django.dispatch import Signal
from django.template import Library
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from clx.app import cache as cache_registry
from clx.app import permissions as permission_registry
from clx.app import search as search_registry
from clx.app.scripts import (
    DECLARATION,
    REGISTRATION,
    scripts_bodies,
    scripts_dirs,
)
from clx.celery import app as celery_app

Card = dict[str, Any]
_Def = ast.FunctionDef | ast.AsyncFunctionDef

REPO_ROOT = Path(settings.BASE_DIR).resolve().parent
TEMPLATES_DIR = Path(settings.BASE_DIR) / "app" / "templates"

BACKEND_LAYERS = (
    ("selector", "clx.app.selectors"),
    ("service", "clx.app.services"),
)

REFERENCE_KINDS = {
    "service": "calls",
    "selector": "calls",
    "task": "queues",
    "cache-key": "uses",
}

EXCLUDED_VIEW_MODULES = {
    "django.views.static",
    "django.contrib.staticfiles.views",
}

DECORATOR_METHODS = {
    "require_GET": ("GET",),
    "require_POST": ("POST",),
    "require_safe": ("GET", "HEAD"),
}

COTTON_BUILTIN_TAGS = {"vars", "slot", "component"}

TAG_USE = re.compile(r"<c-([A-Za-z0-9.-]+)")
CVARS = re.compile(r"<c-vars\s+([^>]*?)/?>", re.S)
CVARS_ATTR = re.compile(r"([:A-Za-z0-9_-]+)(?:=\"[^\"]*\"|='[^']*')?")
EXTENDS = re.compile(r"{%\s*extends\s+[\"']([^\"']+)[\"']")
BLOCK = re.compile(r"{%\s*block\s+([A-Za-z0-9_]+)")
HTTP_METHOD = re.compile(r"[\"'](GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)[\"']")


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


def _registration_kind(match: "re.Match[str]") -> str:
    """Whether a REGISTRATION match is an Alpine.store or Alpine.data."""
    return "Alpine.store" if "store" in match.group(0) else "Alpine.data"


def _chip(kind: str, label: str) -> dict[str, str]:
    """One card chip."""
    return {"kind": kind, "label": label}


def _ref(kind: str, ident: str) -> dict[str, str]:
    """One forward reference to another card."""
    return {"kind": kind, "id": ident}


def _signature(node: _Def) -> str:
    """A function's signature as written in the source."""
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"({ast.unparse(node.args)}){returns}"


def _decorators(node: _Def | ast.ClassDef) -> list[str]:
    """A definition's decorators as written in the source."""
    return [f"@{ast.unparse(item)}" for item in node.decorator_list]


def _segment(info: ModuleInfo, node: _Def | ast.ClassDef) -> str:
    """A definition's source text, decorators included."""
    start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    end = node.end_lineno or node.lineno
    return "\n".join(info.lines[start - 1 : end])


def _assign_lines(info: ModuleInfo) -> dict[str, int]:
    """Line numbers of the module's top-level assignments, by name."""
    lines: dict[str, int] = {}
    for node in info.tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    lines.setdefault(target.id, node.lineno)
        elif isinstance(node, ast.AnnAssign) and isinstance(
            node.target, ast.Name
        ):
            lines.setdefault(node.target.id, node.lineno)
    return lines


def _dict_key_lines(info: ModuleInfo, name: str) -> dict[str, int]:
    """Line numbers of a top-level dict assignment's literal keys."""
    for node in info.tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(
            node.target, ast.Name
        ):
            targets = [node.target.id]
        else:
            continue
        if name not in targets or not isinstance(node.value, ast.Dict):
            continue
        return {
            key.value: key.lineno
            for key in node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
    return {}


def _field_desc(field: "Field[Any, Any]") -> str:
    """A model field described the way it is declared."""
    args: list[str] = []
    related = getattr(field, "related_model", None)
    if field.is_relation and isinstance(related, type):
        args.append(related.__name__)
        on_delete = getattr(
            getattr(field, "remote_field", None), "on_delete", None
        )
        if on_delete is not None:
            args.append(on_delete.__name__)
        related_name = getattr(field.remote_field, "related_name", None)
        if related_name:
            args.append(f"related_name={related_name}")
    else:
        max_length = getattr(field, "max_length", None)
        if max_length:
            args.append(f"max_length={max_length}")
    if field.choices:
        args.append(f"choices={len(list(field.choices))}")
    if field.null:
        args.append("null=True")
    if field.blank:
        args.append("blank=True")
    if field.unique:
        args.append("unique=True")
    if field.has_default() and not callable(field.default):
        args.append(f"default={field.default!r}")
    return f"{type(field).__name__}({', '.join(args)})"


def _decorator_methods(node: _Def) -> list[str]:
    """The HTTP methods a view's require_* decorators allow."""
    methods: dict[str, None] = {}
    for text in (ast.unparse(item) for item in node.decorator_list):
        if text in DECORATOR_METHODS:
            for method in DECORATOR_METHODS[text]:
                methods.setdefault(method)
        elif text.startswith("require_http_methods"):
            for method in HTTP_METHOD.findall(text):
                methods.setdefault(method)
    return list(methods)


def _package_modules(dotted: str) -> Iterator[tuple[str, ModuleType]]:
    """Import and yield a package's direct submodules by stem, in order."""
    package = import_module(dotted)
    paths = list(getattr(package, "__path__", []))
    for entry in sorted(iter_modules(paths), key=lambda m: m.name):
        if entry.name.startswith("_"):
            continue
        yield entry.name, import_module(f"{dotted}.{entry.name}")


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


def _signal_candidates() -> list[tuple[str, Any]]:
    """Every signal instance the standard Django signal modules expose."""
    candidates: list[tuple[str, Any]] = []
    for dotted in ("django.db.models.signals", "django.core.signals"):
        module = import_module(dotted)
        for attr, value in vars(module).items():
            if isinstance(value, Signal):
                candidates.append((attr, value))
    return candidates


def _signal_receivers(signal: Any) -> list[tuple[Any, Any]]:
    """The live (lookup key, receiver) pairs connected to a signal."""
    receivers: list[tuple[Any, Any]] = []
    for entry in getattr(signal, "receivers", []):
        try:
            key, ref = entry[0], entry[1]
        except (IndexError, TypeError):
            continue
        target = ref() if isinstance(ref, weakref.ReferenceType) else ref
        if target is not None:
            receivers.append((key, target))
    return receivers


def _used_tags(text: str) -> list[str]:
    """The cotton tags a template's markup references, in order."""
    return [
        f"c-{tag}"
        for tag in dict.fromkeys(TAG_USE.findall(text))
        if tag not in COTTON_BUILTIN_TAGS
    ]


class _Extractor:
    """One parse of the codebase, shared by the inventory and the checks."""

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


class _Inventory:
    """Builds every card the codebase explorer's inventory serves."""

    def __init__(self, extractor: _Extractor | None = None) -> None:
        self.ex = extractor or _Extractor()
        self.items: list[Card] = []
        self.by_id: dict[str, Card] = {}
        self._import_maps: dict[str, dict[str, tuple[str, str, str]]] = {}
        self.permission_ids: dict[str, str] = {}
        self.scope_ids: dict[str, str] = {}
        self.cache_key_ids: dict[str, str] = {}
        self.cache_value_ids: dict[str, str] = {}
        self.task_ids: dict[str, str] = {}
        self.task_ids_by_dotted: dict[str, str] = {}
        self.template_ids: dict[str, str] = {}
        self.model_ids: dict[type[Model], str] = {}
        self.tag_ids: dict[str, str] = {}
        self._uses: list[tuple[Card, list[str]]] = []
        self._resolvable: list[tuple[Card, str, str]] = []
        self._page_surfaces: dict[str, str] = {}

    def build(self) -> list[Card]:
        """Assemble the full inventory in dependency order."""
        self.build_permissions()
        self.build_scopes()
        self.build_cache_keys()
        self.build_search_indexes()
        self.build_templates()
        self.build_models()
        self.build_tasks()
        self.build_beat_entries()
        self.build_functions()
        self.build_urls()
        self.build_mcp_tools()
        self.build_commands()
        self.build_wiring()
        self.attach_uses()
        self.attach_references()
        return self.items

    def add(
        self,
        layer: str,
        name: str,
        *,
        ident: str | None = None,
        path: str | None = None,
        line: int | None = None,
        group: dict[str, str] | None = None,
        signature: str | None = None,
        doc: str | None = None,
        chips: list[dict[str, str]] | None = None,
        details: dict[str, str] | None = None,
        refs: list[dict[str, str]] | None = None,
        source: str | None = None,
    ) -> Card:
        """Append one card and index it by id."""
        card: Card = {
            "id": ident or f"{layer}:{path}:{name}",
            "layer": layer,
            "name": name,
            "path": path,
            "line": line,
            "group": group,
            "signature": signature,
            "doc": doc,
            "chips": chips or [],
            "details": details or {},
            "refs": refs or [],
            "source": source,
        }
        self.items.append(card)
        self.by_id[card["id"]] = card
        return card

    def module(self, file: str | None) -> ModuleInfo:
        """The parsed source of a python module, from the shared extractor."""
        return self.ex.module(file)

    def template(self, path: Path) -> _TemplateInfo:
        """The text and script bodies of a template, from the extractor."""
        return self.ex.template(path)

    def build_permissions(self) -> None:
        """Cards for every permission and group in the registry."""
        info = self.module(permission_registry.__file__)
        permission_lines = _dict_key_lines(info, "PERMISSIONS")
        for codename, description in permission_registry.PERMISSIONS.items():
            card = self.add(
                "permission",
                f"app.{codename}",
                path=info.rel,
                line=permission_lines.get(codename),
                details={"description": description},
            )
            self.permission_ids[codename] = card["id"]
            self.permission_ids[f"app.{codename}"] = card["id"]
        group_lines = _dict_key_lines(info, "GROUPS")
        for group_name, codenames in permission_registry.GROUPS.items():
            self.add(
                "group",
                group_name,
                path=info.rel,
                line=group_lines.get(group_name),
                details={
                    "permissions": ", ".join(
                        f"app.{codename}" for codename in codenames
                    )
                },
                refs=[
                    _ref("grants", self.permission_ids[codename])
                    for codename in codenames
                    if codename in self.permission_ids
                ],
            )

    def build_scopes(self) -> None:
        """Cards for every API scope, with its configured rate limit."""
        info = self.module(permission_registry.__file__)
        scope_lines = _dict_key_lines(info, "API_SCOPES")
        window = settings.API_RATE_LIMIT_WINDOW_SECONDS
        for scope, description in permission_registry.API_SCOPES.items():
            limit = settings.API_RATE_LIMIT_PER_SCOPE.get(
                scope, settings.API_RATE_LIMIT_PER_SCOPE_DEFAULT
            )
            card = self.add(
                "scope",
                scope,
                path=info.rel,
                line=scope_lines.get(scope),
                details={
                    "description": description,
                    "rate limit": f"{limit}/{window}s",
                },
            )
            self.scope_ids[scope] = card["id"]

    def build_cache_keys(self) -> None:
        """Cards for every *_CACHE_KEY constant, with its TTL when set."""
        info = self.module(cache_registry.__file__)
        lines = _assign_lines(info)
        for name, value in vars(cache_registry).items():
            if not name.endswith("_CACHE_KEY") or not isinstance(value, str):
                continue
            details = {"key": value}
            ttl = getattr(
                cache_registry,
                name.removesuffix("_CACHE_KEY") + "_CACHE_TTL",
                None,
            )
            if ttl is not None:
                details["ttl"] = f"{ttl}s"
            card = self.add(
                "cache-key",
                name,
                path=info.rel,
                line=lines.get(name),
                details=details,
            )
            self.cache_key_ids[name] = card["id"]
            self.cache_value_ids[value] = card["id"]

    def build_search_indexes(self) -> None:
        """Cards for every index contract search.py declares."""
        info = self.module(search_registry.__file__)
        for fname, node in info.functions.items():
            if fname.startswith("_") or not fname.endswith("_index"):
                continue
            alias = str(getattr(search_registry, fname)())
            base = fname.removesuffix("_index")
            mapping = getattr(search_registry, f"{base.upper()}_MAPPING", None)
            builder = getattr(search_registry, f"{base}_document", None)
            details = {"alias": alias}
            if builder is not None:
                details["document builder"] = builder.__name__
            self.add(
                "search-index",
                alias,
                path=info.rel,
                line=node.lineno,
                doc=ast.get_docstring(node),
                details=details,
                source=(
                    json.dumps(mapping, indent=2)
                    if mapping is not None
                    else _segment(info, node)
                ),
            )

    def build_templates(self) -> None:
        """Cards for components, layouts, pages, and script registrations."""
        self.build_components()
        self.build_layouts()
        self.build_pages()
        self.build_scripts()

    def build_components(self) -> None:
        """One card per cotton template, tagged and namespaced."""
        for path in sorted((TEMPLATES_DIR / "cotton").rglob("*.html")):
            rel_name = path.relative_to(TEMPLATES_DIR).as_posix()
            parts = (
                path.relative_to(TEMPLATES_DIR / "cotton")
                .with_suffix("")
                .parts
            )
            tag = "c-" + ".".join(p.replace("_", "-") for p in parts)
            surface = parts[0] if len(parts) > 1 else "primitives"
            info = self.template(path)
            text = info.text
            details = {"tag": f"<{tag} />"}
            cvars = CVARS.search(text)
            if cvars:
                props = [
                    attr.lstrip(":")
                    for attr in CVARS_ATTR.findall(cvars.group(1))
                    if attr.strip(":")
                ]
                if props:
                    details["props"] = ", ".join(dict.fromkeys(props))
            chips = []
            for body in info.bodies:
                for match in REGISTRATION.finditer(body):
                    kind = _registration_kind(match).removeprefix("Alpine.")
                    chips.append(
                        _chip("registers", f"{kind}:{match.group(1)}")
                    )
            card = self.add(
                "component",
                rel_name,
                path=_rel(path),
                group={"kind": "pages", "name": surface},
                chips=chips,
                details=details,
                source=text,
            )
            self.template_ids[rel_name] = card["id"]
            self.tag_ids[tag] = card["id"]
            self._uses.append((card, _used_tags(text)))

    def build_layouts(self) -> None:
        """One card per layout, listing the blocks it defines."""
        for path in sorted((TEMPLATES_DIR / "layouts").glob("*.html")):
            rel_name = path.relative_to(TEMPLATES_DIR).as_posix()
            text = self.template(path).text
            details = {}
            blocks = list(dict.fromkeys(BLOCK.findall(text)))
            if blocks:
                details["blocks"] = ", ".join(blocks)
            extends = EXTENDS.search(text)
            if extends:
                details["extends"] = extends.group(1)
            card = self.add(
                "layout",
                rel_name,
                path=_rel(path),
                details=details,
                source=text,
            )
            self.template_ids[rel_name] = card["id"]
            self._uses.append((card, _used_tags(text)))

    def build_pages(self) -> None:
        """One card per page template, whatever its file type."""
        for path in sorted((TEMPLATES_DIR / "pages").rglob("*")):
            if not path.is_file():
                continue
            rel_name = path.relative_to(TEMPLATES_DIR).as_posix()
            parts = path.relative_to(TEMPLATES_DIR / "pages").parts
            group = (
                {"kind": "pages", "name": parts[0]} if len(parts) > 1 else None
            )
            text = self.template(path).text
            details = {}
            refs = []
            extends = EXTENDS.search(text)
            if extends:
                details["extends"] = extends.group(1)
                target = self.template_ids.get(extends.group(1))
                if target:
                    refs.append(_ref("extends", target))
            card = self.add(
                "page",
                rel_name,
                path=_rel(path),
                group=group,
                details=details,
                refs=refs,
                source=text,
            )
            self.template_ids[rel_name] = card["id"]
            self._uses.append((card, _used_tags(text)))

    def build_scripts(self) -> None:
        """One card per Alpine registration or top-level bundle declaration."""
        for directory in scripts_dirs():
            for path in sorted(directory.rglob("*.html")):
                info = self.template(path)
                text = info.text
                template_name = path.relative_to(directory).as_posix()
                origin_id = self.template_ids.get(template_name)
                origin_card = self.by_id.get(origin_id) if origin_id else None
                entries: dict[str, tuple[str, str, str]] = {}
                for body in info.bodies:
                    for match in REGISTRATION.finditer(body):
                        entries.setdefault(
                            match.group(1),
                            (_registration_kind(match), match.group(0), body),
                        )
                    for match in DECLARATION.finditer(body):
                        kind = " ".join(match.group(0).split()[:-1])
                        entries.setdefault(
                            match.group(1), (kind, match.group(0), body)
                        )
                for name, (kind, needle, body) in entries.items():
                    offset = text.find(needle)
                    line = (
                        text.count("\n", 0, offset) + 1
                        if offset >= 0
                        else None
                    )
                    self.add(
                        "script",
                        name,
                        ident=f"script:{_rel(path)}:{name}",
                        path=_rel(path),
                        line=line,
                        group=origin_card["group"] if origin_card else None,
                        details={"kind": kind},
                        refs=(
                            [_ref("origin", origin_id)] if origin_id else []
                        ),
                        source=body,
                    )

    def build_models(self) -> None:
        """One card per model class, abstract bases included."""
        pending: list[tuple[Card, type[Model]]] = []
        for stem, module in _package_modules("clx.app.models"):
            info = self.module(module.__file__)
            for cname, node in info.classes.items():
                cls = getattr(module, cname, None)
                if not (isinstance(cls, type) and issubclass(cls, Model)):
                    continue
                if cls.__module__ != module.__name__:
                    continue
                meta = cls._meta
                details: dict[str, str] = {}
                for field in [*meta.local_fields, *meta.local_many_to_many]:
                    details[field.name] = _field_desc(field)
                for attr, value in vars(cls).items():
                    if isinstance(value, property) and value.fget:
                        doc = (value.fget.__doc__ or "").strip()
                        details[f"{attr} (property)"] = (
                            doc.splitlines()[0] if doc else ""
                        )
                card = self.add(
                    "model",
                    cname,
                    path=info.rel,
                    line=node.lineno,
                    group={"kind": "domain", "name": stem},
                    doc=ast.get_docstring(node),
                    chips=(
                        [_chip("abstract", "abstract")]
                        if meta.abstract
                        else []
                    ),
                    details=details,
                    source=_segment(info, node),
                )
                self.model_ids[cls] = card["id"]
                pending.append((card, cls))
        for card, cls in pending:
            meta = cls._meta
            for field in [*meta.local_fields, *meta.local_many_to_many]:
                related = getattr(field, "related_model", None)
                if not isinstance(related, type):
                    continue
                target = self.model_ids.get(related)
                if target:
                    card["refs"].append(_ref("relates", target))

    def build_tasks(self) -> None:
        """One card per registered celery task defined in this app."""
        import_module("clx.app.tasks")
        beat = {
            str(entry["task"])
            for entry in settings.CELERY_BEAT_SCHEDULE.values()
        }
        for dotted in sorted(celery_app.tasks):
            if not dotted.startswith("clx."):
                continue
            task = celery_app.tasks[dotted]
            fn: Any = getattr(task, "__wrapped__", None) or getattr(
                task, "run", None
            )
            module_name = getattr(fn, "__module__", "")
            if not module_name.startswith("clx."):
                continue
            module = import_module(module_name)
            info = self.module(module.__file__)
            node = info.functions.get(fn.__name__)
            if node is None:
                continue
            card = self.add(
                "task",
                fn.__name__,
                path=info.rel,
                line=node.lineno,
                group={
                    "kind": "domain",
                    "name": module_name.rsplit(".", 1)[1],
                },
                signature=_signature(node),
                doc=ast.get_docstring(node),
                chips=[_chip("beat", "beat")] if dotted in beat else [],
                details={"task": dotted},
                source=_segment(info, node),
            )
            self.task_ids[fn.__name__] = card["id"]
            self.task_ids_by_dotted[dotted] = card["id"]
            self._resolvable.append((card, module_name, fn.__name__))

    def build_beat_entries(self) -> None:
        """One card per beat schedule entry, linked to the task it runs."""
        module = import_module("clx.settings")
        info = self.module(module.__file__)
        lines = _dict_key_lines(info, "CELERY_BEAT_SCHEDULE")
        for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
            dotted = str(entry["task"])
            schedule = entry.get("schedule")
            target = self.task_ids_by_dotted.get(dotted)
            self.add(
                "beat-entry",
                name,
                path=info.rel,
                line=lines.get(name),
                details={
                    "task": dotted,
                    "schedule": (
                        f"{schedule}s"
                        if isinstance(schedule, int | float)
                        else str(schedule)
                    ),
                },
                refs=[_ref("runs", target)] if target else [],
            )

    def build_functions(self) -> None:
        """One card per public selector and service function."""
        for layer, package in BACKEND_LAYERS:
            for stem, module in _package_modules(package):
                info = self.module(module.__file__)
                for fname, node in info.functions.items():
                    if fname.startswith("_"):
                        continue
                    fn = getattr(module, fname, None)
                    decorators = _decorators(node)
                    chips = []
                    if any(d.endswith("atomic") for d in decorators):
                        chips.append(_chip("decorator", "atomic"))
                    refs = []
                    for value in getattr(fn, "busts_cache", ()):
                        target = self.cache_value_ids.get(value)
                        if target:
                            refs.append(_ref("busts", target))
                    details = {}
                    if decorators:
                        details["decorators"] = ", ".join(decorators)
                    card = self.add(
                        layer,
                        fname,
                        path=info.rel,
                        line=node.lineno,
                        group={"kind": "domain", "name": stem},
                        signature=_signature(node),
                        doc=ast.get_docstring(node),
                        chips=chips,
                        details=details,
                        refs=refs,
                        source=_segment(info, node),
                    )
                    self._resolvable.append((card, module.__name__, fname))

    def build_urls(self) -> None:
        """One card per routed endpoint and view, externals flagged."""
        groups: dict[Any, dict[str, Any]] = {}
        for fact, callback in self.ex.routes_with_callbacks():
            module_name = fact.module
            if module_name in EXCLUDED_VIEW_MODULES:
                continue
            key: Any = callback
            if module_name.startswith(("clx.app.api.", "clx.app.views.")):
                key = f"{module_name}.{callback.__name__}"
            entry = groups.setdefault(
                key, {"routes": [], "names": [], "callback": callback}
            )
            entry["routes"].append(fact.route)
            if fact.name:
                entry["names"].append(fact.name)
        for entry in groups.values():
            callback = entry["callback"]
            details = {"route": " · ".join(dict.fromkeys(entry["routes"]))}
            names = list(dict.fromkeys(entry["names"]))
            if names:
                details["url name"] = " · ".join(names)
            module_name = getattr(callback, "__module__", "")
            if module_name.startswith("clx.app.api."):
                self._emit_endpoint(module_name, callback, details)
            elif module_name.startswith("clx.app.views."):
                self._emit_view(module_name, callback, details)
            else:
                self._emit_external_view(callback, details)
        for template_name, surface in self._page_surfaces.items():
            target = self.template_ids.get(template_name)
            card = self.by_id.get(target) if target else None
            if card and card["layer"] == "page" and card["group"] is None:
                card["group"] = {"kind": "pages", "name": surface}

    def _emit_endpoint(
        self, module_name: str, callback: Any, details: dict[str, str]
    ) -> None:
        """One endpoint card, its auth contract read off the api_auth stash."""
        module = import_module(module_name)
        info = self.module(module.__file__)
        node = info.functions.get(callback.__name__)
        if node is None:
            return
        chips = [
            _chip("method", method) for method in _decorator_methods(node)
        ]
        refs = []
        stash = getattr(callback, "api_auth", None)
        if stash:
            for method in stash["methods"]:
                chips.append(_chip("auth", method))
            for scope in stash["scopes"]:
                chips.append(_chip("scope", scope))
                target = self.scope_ids.get(scope)
                if target:
                    refs.append(_ref("scoped", target))
            for perm in stash["perms"]:
                chips.append(_chip("perm", perm))
                target = self.permission_ids.get(perm)
                if target:
                    refs.append(_ref("requires", target))
            if stash["rate"]:
                chips.append(
                    _chip("rate", f"{stash['rate'][0]}/{stash['rate'][1]}s")
                )
        else:
            chips.append(_chip("auth", "public"))
        decorators = _decorators(node)
        if decorators:
            details["decorators"] = ", ".join(decorators)
        card = self.add(
            "endpoint",
            callback.__name__,
            path=info.rel,
            line=node.lineno,
            group={"kind": "api", "name": module_name.rsplit(".", 1)[1]},
            signature=_signature(node),
            doc=ast.get_docstring(node),
            chips=chips,
            details=details,
            refs=refs,
            source=_segment(info, node),
        )
        self._resolvable.append((card, module_name, callback.__name__))

    def _emit_view(
        self, module_name: str, callback: Any, details: dict[str, str]
    ) -> None:
        """One HTML view card, linked to the page template it renders."""
        module = import_module(module_name)
        info = self.module(module.__file__)
        node = info.functions.get(callback.__name__)
        if node is None:
            return
        surface = module_name.rsplit(".", 1)[1]
        chips = []
        refs = []
        for item in node.decorator_list:
            text = ast.unparse(item)
            if text == "login_required":
                chips.append(_chip("decorator", "login_required"))
            if (
                isinstance(item, ast.Call)
                and ast.unparse(item.func) == "permission_required"
                and item.args
                and isinstance(item.args[0], ast.Constant)
                and isinstance(item.args[0].value, str)
            ):
                perm = item.args[0].value
                chips.append(_chip("perm", perm))
                target = self.permission_ids.get(perm)
                if target:
                    refs.append(_ref("requires", target))
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id == "render"
                and len(sub.args) >= 2
                and isinstance(sub.args[1], ast.Constant)
                and isinstance(sub.args[1].value, str)
            ):
                template_name = sub.args[1].value
                self._page_surfaces.setdefault(template_name, surface)
                target = self.template_ids.get(template_name)
                if target:
                    refs.append(_ref("renders", target))
        decorators = _decorators(node)
        if decorators:
            details["decorators"] = ", ".join(decorators)
        card = self.add(
            "view",
            callback.__name__,
            path=info.rel,
            line=node.lineno,
            group={"kind": "pages", "name": surface},
            signature=_signature(node),
            doc=ast.get_docstring(node),
            chips=chips,
            details=details,
            refs=refs,
            source=_segment(info, node),
        )
        self._resolvable.append((card, module_name, callback.__name__))

    def _emit_external_view(
        self, callback: Any, details: dict[str, str]
    ) -> None:
        """One flagged card for a route served by third-party code."""
        view_class = getattr(callback, "view_class", None)
        target = view_class if view_class is not None else callback
        name = getattr(target, "__name__", "view")
        dotted = f"{getattr(target, '__module__', 'unknown')}.{name}"
        route = details["route"].split(" · ")[0]
        refs = []
        for key, value in (
            getattr(callback, "view_initkwargs", None) or {}
        ).items():
            details[key] = str(value)
            if key == "template_name" and isinstance(value, str):
                template = self.template_ids.get(value)
                if template:
                    refs.append(_ref("renders", template))
        self.add(
            "view",
            name,
            ident=f"view:{dotted}:{route}",
            chips=[_chip("external", "external")],
            details=details,
            refs=refs,
        )

    def build_mcp_tools(self) -> None:
        """One card per registered MCP tool, schema and annotations included."""
        try:
            import_module("clx.mcp.tools")
            base = import_module("clx.mcp.tools.base")
        except ImportError:
            return
        tools: dict[str, Any] = base.TOOLS
        for name in sorted(tools):
            tool = tools[name]
            cls = type(tool)
            module = import_module(cls.__module__)
            info = self.module(module.__file__)
            node = info.classes.get(cls.__name__)
            if node is None:
                continue
            chips = []
            refs = []
            for scope in tool.required_scopes:
                chips.append(_chip("scope", scope))
                target = self.scope_ids.get(scope)
                if target:
                    refs.append(_ref("scoped", target))
            for perm in tool.required_perms:
                chips.append(_chip("perm", perm))
                target = self.permission_ids.get(perm)
                if target:
                    refs.append(_ref("requires", target))
            if tool.rate is not None:
                chips.append(_chip("rate", f"{tool.rate[0]}/{tool.rate[1]}s"))
            if tool.always_listed:
                chips.append(_chip("listed", "always listed"))
            details = {"input schema": json.dumps(tool.input_schema)}
            if tool.annotations is not None:
                details["annotations"] = json.dumps(
                    tool.annotations.model_dump(exclude_none=True)
                )
            card = self.add(
                "mcp-tool",
                tool.name,
                path=info.rel,
                line=node.lineno,
                doc=ast.get_docstring(node),
                chips=chips,
                details=details,
                refs=refs,
                source=_segment(info, node),
            )
            self._resolvable.append((card, cls.__module__, cls.__name__))

    def build_commands(self) -> None:
        """One card per management command."""
        for stem, module in _package_modules("clx.app.management.commands"):
            info = self.module(module.__file__)
            node = info.classes.get("Command")
            if node is None:
                continue
            help_text = str(getattr(module.Command, "help", "") or "")
            card = self.add(
                "command",
                stem,
                path=info.rel,
                line=node.lineno,
                doc=ast.get_docstring(node),
                details={"help": help_text} if help_text else {},
                source=_segment(info, node),
            )
            self._resolvable.append((card, module.__name__, "Command"))

    def build_wiring(self) -> None:
        """Cards for middleware, context processors, signals, tags, checks."""
        self.build_dotted_list("middleware", list(settings.MIDDLEWARE))
        templates = cast("list[dict[str, Any]]", settings.TEMPLATES)
        processors = templates[0]["OPTIONS"]["context_processors"]
        self.build_dotted_list("context-processor", list(processors))
        self.build_signals()
        self.build_templatetags()
        self.build_checks()

    def build_dotted_list(self, layer: str, dotted_paths: list[str]) -> None:
        """One card per settings list entry, externals flagged."""
        for index, dotted in enumerate(dotted_paths, 1):
            module_name, _, attr = dotted.rpartition(".")
            details = {"path": dotted, "order": str(index)}
            if not dotted.startswith("clx."):
                self.add(
                    layer,
                    attr,
                    ident=f"{layer}:{dotted}",
                    chips=[_chip("external", "external")],
                    details=details,
                )
                continue
            module = import_module(module_name)
            info = self.module(module.__file__)
            node: _Def | ast.ClassDef | None = info.classes.get(
                attr
            ) or info.functions.get(attr)
            card = self.add(
                layer,
                attr,
                path=info.rel,
                line=node.lineno if node else None,
                signature=(
                    _signature(node)
                    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                    else None
                ),
                doc=ast.get_docstring(node) if node else None,
                details=details,
                source=_segment(info, node) if node else None,
            )
            if node is not None:
                self._resolvable.append((card, module_name, attr))

    def build_signals(self) -> None:
        """One card per receiver in signals.py, with what it is connected to."""
        module = import_module("clx.app.signals")
        info = self.module(module.__file__)
        candidates = _signal_candidates()
        sender_labels = {id(apps.get_app_config("app")): "AppConfig"}
        for model in apps.get_models():
            sender_labels[id(model)] = model.__name__
        for fname, node in info.functions.items():
            if fname.startswith("_"):
                continue
            fn = getattr(module, fname, None)
            connected: dict[str, None] = {}
            for signal_name, signal in candidates:
                for key, receiver in _signal_receivers(signal):
                    if receiver is not fn:
                        continue
                    label = signal_name
                    try:
                        sender = sender_labels.get(key[1])
                    except (IndexError, TypeError):
                        sender = None
                    if sender:
                        label = f"{signal_name} (sender={sender})"
                    connected.setdefault(label)
            card = self.add(
                "signal",
                fname,
                path=info.rel,
                line=node.lineno,
                signature=_signature(node),
                doc=ast.get_docstring(node),
                details=(
                    {"signal": ", ".join(connected)} if connected else {}
                ),
                source=_segment(info, node),
            )
            self._resolvable.append((card, module.__name__, fname))

    def build_templatetags(self) -> None:
        """One card per registered template tag or filter."""
        for _stem, module in _package_modules("clx.app.templatetags"):
            info = self.module(module.__file__)
            libraries = [
                value
                for value in vars(module).values()
                if isinstance(value, Library)
            ]
            for library in libraries:
                registered = [
                    ("tag", name, fn) for name, fn in library.tags.items()
                ] + [
                    ("filter", name, fn)
                    for name, fn in library.filters.items()
                ]
                for kind, name, fn in registered:
                    node = info.functions.get(getattr(fn, "__name__", ""))
                    card = self.add(
                        "templatetag",
                        name,
                        ident=f"templatetag:{info.rel}:{name}",
                        path=info.rel,
                        line=node.lineno if node else None,
                        signature=_signature(node) if node else None,
                        doc=ast.get_docstring(node) if node else None,
                        details={"kind": kind},
                        source=_segment(info, node) if node else None,
                    )
                    if node is not None:
                        self._resolvable.append(
                            (card, module.__name__, node.name)
                        )

    def build_checks(self) -> None:
        """One card per system check registered from this app."""
        import_module("clx.app.checks")
        checks = set(check_registry.registered_checks) | set(
            check_registry.deployment_checks
        )
        for check in sorted(
            checks, key=lambda item: getattr(item, "__name__", "")
        ):
            module_name = getattr(check, "__module__", "")
            check_name = str(getattr(check, "__name__", ""))
            if not module_name.startswith("clx."):
                continue
            module = import_module(module_name)
            info = self.module(module.__file__)
            node = info.functions.get(check_name)
            if node is None:
                continue
            tags = sorted(getattr(check, "tags", None) or [])
            card = self.add(
                "check",
                check_name,
                path=info.rel,
                line=node.lineno,
                signature=_signature(node),
                doc=ast.get_docstring(node),
                chips=(
                    [_chip("decorator", "deploy")]
                    if check in check_registry.deployment_checks
                    else []
                ),
                details={"tags": ", ".join(tags)} if tags else {},
                source=_segment(info, node),
            )
            self._resolvable.append((card, module_name, check_name))

    def attach_uses(self) -> None:
        """Attach uses refs now that every component card exists."""
        for card, tags in self._uses:
            for tag in tags:
                target = self.tag_ids.get(tag)
                if target and target != card["id"]:
                    card["refs"].append(_ref("uses", target))

    def imports_for(self, info: ModuleInfo) -> dict[str, tuple[str, str, str]]:
        """A module's imported first-party names, resolved to their real homes."""
        if info.rel not in self._import_maps:
            mapping: dict[str, tuple[str, str, str]] = {}
            for node in ast.walk(info.tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.level or not (node.module or "").startswith("clx."):
                    continue
                source_module = str(node.module)
                for alias in node.names:
                    local = alias.asname or alias.name
                    obj = getattr(
                        import_module(source_module), alias.name, None
                    )
                    if isinstance(obj, ModuleType):
                        mapping[local] = ("mod", obj.__name__, "")
                    else:
                        mapping[local] = ("sym", source_module, alias.name)
            self._import_maps[info.rel] = mapping
        return self._import_maps[info.rel]

    def classify(
        self, module_name: str, symbol: str
    ) -> tuple[str, str] | None:
        """Map a referenced first-party name to a target card layer and id."""
        if _in_package(module_name, "clx.app.cache"):
            target = self.cache_key_ids.get(symbol)
            return ("cache-key", target) if target else None
        if _in_package(module_name, "clx.app.tasks"):
            target = self.task_ids.get(symbol)
            return ("task", target) if target else None
        for layer, package in BACKEND_LAYERS:
            if not _in_package(module_name, package):
                continue
            real_module = module_name
            if module_name == package:
                obj = getattr(import_module(module_name), symbol, None)
                real_module = getattr(obj, "__module__", module_name)
            file = getattr(import_module(real_module), "__file__", None)
            if file is None:
                return None
            return (layer, f"{layer}:{_rel(file)}:{symbol}")
        return None

    def _targets_for(
        self, info: ModuleInfo, sub: ast.AST, expanding: frozenset[str]
    ) -> list[tuple[str, str]]:
        """The targets one AST node contributes, private helpers expanded."""
        imports = self.imports_for(info)
        if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
            entry = imports.get(sub.value.id)
            if entry and entry[0] == "mod":
                target = self.classify(entry[1], sub.attr)
                return [target] if target else []
        if not isinstance(sub, ast.Name):
            return []
        entry = imports.get(sub.id)
        if entry and entry[0] == "sym":
            target = self.classify(entry[1], entry[2])
            return [target] if target else []
        helper = info.functions.get(sub.id)
        if (
            helper is not None
            and sub.id.startswith("_")
            and sub.id not in expanding
        ):
            return self.referenced(info, helper, expanding | {sub.id})
        return []

    def referenced(
        self,
        info: ModuleInfo,
        node: _Def | ast.ClassDef,
        expanding: frozenset[str] = frozenset(),
    ) -> list[tuple[str, str]]:
        """A definition's first-party targets, attributed through private helpers."""
        found: list[tuple[str, str]] = []
        seen: set[str] = set()
        for statement in node.body:
            for sub in ast.walk(statement):
                for target in self._targets_for(info, sub, expanding):
                    if target[1] not in seen:
                        seen.add(target[1])
                        found.append(target)
        return found

    def attach_references(self) -> None:
        """Attach import-reference refs once every card id is known."""
        for card, module_name, qualname in self._resolvable:
            module = import_module(module_name)
            info = self.module(module.__file__)
            node: _Def | ast.ClassDef | None = info.functions.get(
                qualname
            ) or info.classes.get(qualname)
            if node is None:
                continue
            existing = {(r["kind"], r["id"]) for r in card["refs"]}
            for layer, target in self.referenced(info, node):
                if target not in self.by_id or target == card["id"]:
                    continue
                kind = REFERENCE_KINDS[layer]
                if card["layer"] == "task" and layer == "service":
                    kind = "runs"
                if (kind, target) in existing:
                    continue
                existing.add((kind, target))
                card["refs"].append(_ref(kind, target))


def codebase_facts() -> CodebaseFacts:
    """The fact tables the pattern checks assert over, from one parse."""
    return _Extractor().facts()


def codebase_inventory() -> list[Card]:
    """Every card the admin codebase explorer renders, in build order."""
    return _Inventory().build()
