"""Shared symbol index for lint_docs and build_docs."""

import argparse
import ast
import hashlib
import re
import subprocess
import sys
from pathlib import Path

TEMPLATE_DIRS = {"templates", "template_overrides"}
TEMPLATE_SUFFIXES = {".html", ".js", ".webmanifest", ".txt", ".svg"}

EXTENDS = re.compile(r"{%\s*extends\s+[\"']([^\"']+)[\"']")
INCLUDE = re.compile(r"{%\s*include\s+[\"']([^\"']+)[\"']")
COTTON = re.compile(r"<c-([a-zA-Z0-9._-]+)")
BLOCK = re.compile(r"{%\s*block\s+([a-zA-Z0-9_]+)\s*%}")
ENDBLOCK = re.compile(r"{%\s*endblock[^%]*%}")

IGNORE_DIRS = {".git", ".venv", "venv", "node_modules", "build", "dist"}

REFERENCE = re.compile(r"sym:((?:[0-9a-f]{12}\+?)(?:,[0-9a-f]{12}\+?)*)")


def common_parser():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--docs",
        type=Path,
        default=Path("docs"),
        help="docs directory (default: docs)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository root (default: cwd)",
    )
    parser.add_argument(
        "--package",
        type=Path,
        action="append",
        help="package to index; repeatable (default: auto-detect)",
    )
    return parser


def ignored(path, repo):
    parts = path.relative_to(repo).parts
    return bool(set(parts) & IGNORE_DIRS) or any(
        part.startswith(".") for part in parts
    )


def find_template_roots(repo):
    return [
        p
        for p in sorted(repo.rglob("*"))
        if p.is_dir() and p.name in TEMPLATE_DIRS and not ignored(p, repo)
    ]


def template_name(path, roots):
    for root in roots:
        if root in path.parents:
            return path.relative_to(root).as_posix()
    return path.name


def cotton_path(tag):
    return "cotton/" + tag.replace(".", "/").replace("-", "_") + ".html"


def normalize(text):
    return " ".join(text.split())


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def block_bodies(text):
    """Map each block name to its source and lines, handling nesting by depth."""
    bodies, stack = {}, []
    tokens = sorted(
        [(m.start(), m.end(), m.group(1)) for m in BLOCK.finditer(text)]
        + [(m.start(), m.end(), None) for m in ENDBLOCK.finditer(text)]
    )
    for start, end, name in tokens:
        if name:
            stack.append((name, start, end))
        elif stack:
            opened, tag_start, body_start = stack.pop()
            bodies.setdefault(
                opened,
                (
                    text[body_start:start],
                    line_of(text, tag_start),
                    line_of(text, start),
                ),
            )
    return bodies


def tracked_files(repo):
    """Whatever the repo itself considers a file worth having."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return [repo / name for name in out.split("\0") if name]
    except (OSError, subprocess.CalledProcessError):
        return [
            p
            for p in sorted(repo.rglob("*"))
            if p.is_file() and not ignored(p, repo)
        ]


def file_content(path):
    data = path.read_bytes()
    try:
        return normalize(data.decode())
    except UnicodeDecodeError:
        return hashlib.sha1(data).hexdigest()


def index_templates(repo, roots=None):
    roots = roots or find_template_roots(repo)
    defs, edges, seen = {}, [], set()
    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in TEMPLATE_SUFFIXES:
                continue
            name = template_name(path, roots)
            seen.add(path)
            rel = path.relative_to(repo).as_posix()
            text = path.read_text()
            defs[name] = ("template", normalize(text), (rel, None, None))
            for block, (body, start, end) in block_bodies(text).items():
                defs[f"{name}#{block}"] = (
                    "block",
                    normalize(body),
                    (rel, start, end),
                )
            for match in EXTENDS.finditer(text):
                edges.append(
                    (
                        name,
                        "extends",
                        match.group(1),
                        line_of(text, match.start()),
                    )
                )
            for match in INCLUDE.finditer(text):
                edges.append(
                    (
                        name,
                        "includes",
                        match.group(1),
                        line_of(text, match.start()),
                    )
                )
            for match in COTTON.finditer(text):
                if match.group(1) != "vars":
                    edges.append(
                        (
                            name,
                            "uses",
                            cotton_path(match.group(1)),
                            line_of(text, match.start()),
                        )
                    )
    return defs, edges, seen


def find_roots(repo, tracked):
    """Top-level packages, or failing that the dirs holding tracked python.

    Never falls back to the repo root: an unqualified rglob there would walk
    the virtualenv, which is thousands of files that are not this codebase.
    """
    roots = [
        p
        for p in sorted(repo.iterdir())
        if p.is_dir()
        and not p.name.startswith(".")
        and p.name not in IGNORE_DIRS
        and (p / "__init__.py").exists()
    ]
    if roots:
        return roots
    tops = {
        repo / path.relative_to(repo).parts[0]
        for path in tracked
        if path.suffix == ".py" and len(path.relative_to(repo).parts) > 1
    }
    return sorted(tops)


DEFS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def digest(text, n=6):
    return hashlib.sha1(text.encode()).hexdigest()[:n]


def short_id(identity, content=None):
    """Identity in the first half, content in the second.

    A changed body keeps the identity half and changes the content half, so
    a citation that no longer resolves can still be traced to the symbol it
    used to name.
    """
    return digest(identity) + digest(
        content if content is not None else identity
    )


SKIP_DIRS = {"migrations", "__pycache__"}


def skipped(path):
    return bool(SKIP_DIRS & set(path.parts))


def module_name(path, repo):
    rel = path.relative_to(repo).with_suffix("")
    return ".".join(p for p in rel.parts if p != "__init__")


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def assigned_names(node):
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def assign_exprs(node):
    """An assignment's expressions, minus the plain names it binds.

    `X = {...}` is the definition of X, already indexed as a var. Walking the
    target as an expression too would mint a second symbol -- a refs edge from
    the module to a name it merely assigns -- carrying no fact the var does
    not. Subscript and attribute targets are kept: `d[k] = v` really does read
    `d`.
    """
    if isinstance(node, ast.Assign):
        keep = [t for t in node.targets if not isinstance(t, ast.Name)]
        return [*keep, node.value]
    if isinstance(node, ast.AnnAssign):
        parts = [node.annotation]
        if not isinstance(node.target, ast.Name):
            parts.append(node.target)
        if node.value is not None:
            parts.append(node.value)
        return parts
    return [node]


def walk_exprs(node, calls, refs, strings):
    if isinstance(node, DEFS):
        return
    if isinstance(node, ast.Call):
        name = dotted(node.func)
        if name:
            calls.append((name, node.lineno))
        else:
            walk_exprs(node.func, calls, refs, strings)
        for arg in node.args:
            walk_exprs(arg, calls, refs, strings)
        for kw in node.keywords:
            walk_exprs(kw.value, calls, refs, strings)
        return
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        strings.append((node.value, node.lineno))
        return
    if isinstance(node, (ast.Name | ast.Attribute)):
        name = dotted(node)
        if name:
            refs.append((name, node.lineno))
            return
    for child in ast.iter_child_nodes(node):
        walk_exprs(child, calls, refs, strings)


class Module:
    def __init__(self, path, repo):
        self.name = module_name(path, repo)
        self.rel = path.relative_to(repo).as_posix()
        self.tree = ast.parse(path.read_text())
        self.imports = {}
        self.defs = {}
        self.calls = []
        self.refs = []
        self.strings = []
        self._imports()
        self._walk(self.tree, prefix="", owner=self.name)

    def _imports(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.imports[a.asname or a.name] = a.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                for a in node.names:
                    self.imports[a.asname or a.name] = (
                        f"{node.module}.{a.name}"
                    )

    def _walk(self, node, prefix, owner, in_function=False):
        calls, refs, strings = [], [], []
        for child in getattr(node, "body", []):
            for part in assign_exprs(child):
                walk_exprs(part, calls, refs, strings)
        self.calls += [(name, owner, line) for name, line in calls]
        self.refs += [(name, owner, line) for name, line in refs]
        self.strings += [(text, owner, line) for text, line in strings]

        for child in getattr(node, "body", []):
            if isinstance(child, DEFS):
                qual = f"{prefix}{child.name}"
                kind = "class" if isinstance(child, ast.ClassDef) else "def"
                self.defs[qual] = (
                    kind,
                    ast.dump(child),
                    child.lineno,
                    child.end_lineno,
                )
                nested = in_function or kind == "def"
                self._walk(child, f"{qual}.", f"{self.name}.{qual}", nested)
            elif not in_function:
                for name in assigned_names(child):
                    self.defs[f"{prefix}{name}"] = (
                        "var",
                        ast.dump(child),
                        child.lineno,
                        child.end_lineno,
                    )

    def resolve(self, expr, index, owner=""):
        head, _, rest = expr.partition(".")
        if head in ("self", "cls") and rest:
            candidate = f"{owner.rpartition('.')[0]}.{rest}"
            return candidate if candidate in index else None
        if head in self.imports:
            target = self.imports[head]
            return f"{target}.{rest}" if rest else target
        local = f"{self.name}.{expr}"
        return local if local in index else None


def build(repo, roots=None, docs=None):
    repo = repo.resolve()
    tracked = tracked_files(repo)
    roots = [
        r if r.is_absolute() else (repo / r) for r in (roots or [])
    ] or find_roots(repo, tracked)
    paths = sorted(
        p
        for p in tracked
        if p.suffix == ".py"
        and not skipped(p)
        and any(root in p.parents for root in roots)
    )
    modules = [Module(p, repo) for p in paths]

    index, locs = {}, {}
    for m in modules:
        for qual, (kind, source, start, end) in m.defs.items():
            full = f"{m.name}.{qual}"
            index[full] = (kind, source)
            locs[full] = (m.rel, start, end)

    symbols = {}
    for name, (kind, source) in index.items():
        symbols[short_id(name, source)] = (
            kind,
            name,
            name.rsplit(".", 1)[0],
            locs[name],
        )

    for m in modules:
        for bucket, kind in ((m.calls, "calls"), (m.refs, "refs")):
            for expr, owner, line in bucket:
                target = m.resolve(expr, index, owner)
                if target not in index:
                    continue
                key = f"{owner} {kind} {target}"
                symbols[short_id(key, f"edge:{key}")] = (
                    kind,
                    f"{owner} -> {target}",
                    m.name,
                    (m.rel, line, line),
                )

    templates, tedges, template_paths = index_templates(repo)
    for name, (kind, source, loc) in templates.items():
        symbols[short_id(name, source)] = (
            kind,
            name,
            name.rsplit("/", 1)[0],
            loc,
        )

    for owner, kind, target, line in tedges:
        if target not in templates:
            continue
        key = f"{owner} {kind} {target}"
        symbols[short_id(key, f"edge:{key}")] = (
            kind,
            f"{owner} -> {target}",
            owner.rsplit("/", 1)[0],
            (templates[owner][2][0], line, line),
        )

    for m in modules:
        for text, owner, line in m.strings:
            if text not in templates:
                continue
            key = f"{owner} renders {text}"
            symbols[short_id(key, f"edge:{key}")] = (
                "renders",
                f"{owner} -> {text}",
                m.name,
                (m.rel, line, line),
            )

    claimed = set(paths) | template_paths
    for path in tracked:
        if path in claimed or not path.is_file():
            continue
        if path.stat().st_size == 0:
            continue
        rel = path.relative_to(repo).as_posix()
        if rel.startswith(f"{docs.as_posix()}/") if docs else False:
            continue
        symbols[short_id(rel, file_content(path))] = (
            "file",
            rel,
            rel.rsplit("/", 1)[0] if "/" in rel else ".",
            (rel, None, None),
        )

    identities = {sid[:6] for sid in symbols}
    if len(identities) != len(symbols):
        sys.exit("identity collision detected; widen digest()")
    return symbols
