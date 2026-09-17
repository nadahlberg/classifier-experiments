"""Rename the project identity across the repo, by case and context."""

import argparse
import os
import re
import sys
from pathlib import Path

SOURCE = "starter"
TITLE = SOURCE.capitalize()
UPPER = SOURCE.upper()
TOKEN = re.compile(SOURCE, re.IGNORECASE)
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

PRUNE_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
}
PRUNE_PATHS = {
    "docs",
    "local",
    "references",
    "archive",
    ".claude/worktrees",
    ".claude/skills/sync-codebase",
    ".claude/skills/sync-init",
}
SKIP_PATHS = {"uv.lock", "infra/uv.lock", "tailwindcss"}
SKIP_NAMES = {".env", ".git", ".template-rev"}
SKIP_SUFFIXES = ("tests/test_rename_surface.py", ".min.js")
SKIP_ARTIFACTS = ("app/static/main.css", "app/static/js/main.js")
SKIP_EXTS = {
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".jsonl",
    ".otf",
    ".pdf",
    ".png",
    ".pyc",
    ".ttf",
    ".webp",
    ".woff",
    ".woff2",
}


def iter_files(root: Path):
    """Yield scannable files under root, pruning what apply must not touch."""
    self_path = Path(__file__).resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in PRUNE_DIRS
            and not d.endswith(".egg-info")
            and os.path.normpath(os.path.join(rel_dir, d)) not in PRUNE_PATHS
        )
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = os.path.normpath(os.path.join(rel_dir, name))
            if (
                path.is_symlink()
                or path.resolve() == self_path
                or rel in SKIP_PATHS
                or name in SKIP_NAMES
                or rel.endswith(SKIP_SUFFIXES)
                or rel.endswith(SKIP_ARTIFACTS)
                or path.suffix in SKIP_EXTS
            ):
                continue
            yield path, rel


def read_text(path: Path):
    """Return the file's text, or None for binary or non-UTF-8 content."""
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def classify(content: str, start: int, end: int):
    """Name the context claiming one occurrence, or None when unclaimed."""
    text = content[start:end]
    prev = content[start - 1 : start]
    nxt = content[end : end + 1]
    if prev.isalnum() or nxt.isalnum():
        return None
    if text == TITLE:
        return "title"
    if text == UPPER:
        return "upper" if prev == "_" or nxt == "_" else None
    if text != SOURCE:
        return None
    if nxt == "-":
        return "kebab"
    if prev == "-":
        return None
    if (nxt and nxt in "./*:") or prev == "/":
        return "slug"
    if prev and prev in "\"'" and nxt and nxt in "\"'":
        return "slug"
    if content[start - 3 : start] == "-A ":
        return "slug"
    if (
        content[start - 5 : start] == "from "
        and content[end : end + 7] == " import"
    ):
        return "slug"
    if content[start - 5 : start] == "mypy ":
        return "slug"
    line = content[content.rfind("\n", 0, start) + 1 : start]
    if line.startswith("COPY ") and prev == " ":
        return "slug"
    if line.endswith(": ") and nxt in ("\n", ""):
        return "slug"
    if line == "" and content[end : end + 2] == " =":
        return "slug"
    return None


def render(kind: str, slug: str, display: str) -> str:
    """Return the replacement text for a classified occurrence."""
    if kind == "title":
        return display
    if kind == "upper":
        return slug.upper()
    if kind == "kebab":
        return slug.replace("_", "-")
    return slug


def collect(root: Path):
    """Scan every file and split occurrences into claimed and unclaimed."""
    claimed: list[tuple[Path, str]] = []
    unclaimed: list[str] = []
    total = 0
    for path, rel in iter_files(root):
        content = read_text(path)
        if content is None:
            continue
        for match in TOKEN.finditer(content):
            total += 1
            if classify(content, match.start(), match.end()) is None:
                lineno = content.count("\n", 0, match.start()) + 1
                line_start = content.rfind("\n", 0, match.start()) + 1
                line_end = content.find("\n", match.end())
                if line_end == -1:
                    line_end = len(content)
                excerpt = content[line_start:line_end].strip()
                unclaimed.append(f"{rel}:{lineno}: {excerpt}")
            else:
                claimed.append((path, rel))
    return total, claimed, unclaimed


def scan(root: Path, check: bool) -> int:
    """Report every occurrence and fail --check when any is unclaimed."""
    total, claimed, unclaimed = collect(root)
    for line in unclaimed:
        print(f"unclaimed: {line}")
    files = len({rel for _, rel in claimed})
    print(
        f"{total} occurrences: {len(claimed)} claimed across "
        f"{files} files, {len(unclaimed)} unclaimed."
    )
    if check and unclaimed:
        return 1
    return 0


def substitute(content: str, slug: str, display: str) -> tuple[str, int]:
    """Return the content with every claimed occurrence replaced."""
    parts: list[str] = []
    cursor = 0
    replaced = 0
    for match in TOKEN.finditer(content):
        kind = classify(content, match.start(), match.end())
        if kind is None:
            continue
        parts.append(content[cursor : match.start()])
        parts.append(render(kind, slug, display))
        cursor = match.end()
        replaced += 1
    parts.append(content[cursor:])
    return "".join(parts), replaced


def apply(root: Path, slug: str, display: str) -> int:
    """Replace every claimed occurrence and rename the package directory."""
    if not SLUG_PATTERN.match(slug):
        print(f"invalid slug {slug!r}: must match {SLUG_PATTERN.pattern}")
        return 2
    if TOKEN.search(slug) or TOKEN.search(display):
        print(
            f"invalid name: neither slug {slug!r} nor display {display!r} "
            f"may contain {SOURCE!r} — re-running apply would rename "
            "inside the already-renamed name."
        )
        return 2
    _, claimed, unclaimed = collect(root)
    if unclaimed:
        for line in unclaimed:
            print(f"unclaimed: {line}")
        print("refusing to apply while unclaimed occurrences remain.")
        return 2
    replaced = 0
    files = 0
    for path in dict.fromkeys(path for path, _rel in claimed):
        content = read_text(path)
        if content is None:
            continue
        updated, count = substitute(content, slug, display)
        if updated != content:
            path.write_text(updated, encoding="utf-8")
            files += 1
        replaced += count
    package = root / SOURCE
    renamed = ""
    if package.is_dir():
        package.rename(root / slug)
        renamed = f" Renamed {SOURCE}/ to {slug}/."
    print(f"Replaced {replaced} occurrences in {files} files.{renamed}")
    return 0


def main() -> int:
    """Dispatch the scan or apply subcommand."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    scan_command = commands.add_parser("scan")
    scan_command.add_argument("--root", default=".")
    scan_command.add_argument("--check", action="store_true")
    apply_command = commands.add_parser("apply")
    apply_command.add_argument("--root", default=".")
    apply_command.add_argument("--slug", required=True)
    apply_command.add_argument("--display")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.command == "scan":
        return scan(root, args.check)
    display = args.display or " ".join(
        part.capitalize() for part in args.slug.split("_")
    )
    return apply(root, args.slug, display)


if __name__ == "__main__":
    sys.exit(main())
