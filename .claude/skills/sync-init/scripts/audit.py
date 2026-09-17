"""Report where the initialization surface has drifted from the tree."""

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

INIT = ".claude/skills/initialize-project"
SYNC_SKILL = ".claude/skills/sync-codebase/SKILL.md"
CI_WORKFLOW = ".github/workflows/ci.yml"
VERIFY_HEADING = "## The verify suite"

ROW_GUIDES = {
    "MCP server": "mcp",
    "Admin surface": "admin",
    "infra / Pulumi": "infra",
}
ROWS_WITHOUT_GUIDES = {"reset-database workflow"}
EXPECTED_ABSENT = {".claude/skills/sync-codebase/ledger.json"}
SYMBOL_FILE_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".webmanifest",
    ".yml",
}

BACKTICK = re.compile(r"`([^`\n]+)`")
PATH_UNSAFE = re.compile(r"""[\s<>()"'*${}\[\]|,;=]""")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
STAGE_HEADING = re.compile(r"^## Stage (\d+) — (.+?)\s*$", re.M)
PROGRESS_BOX = re.compile(r"^- \[[ x]\] (\d+)\. (.+?)\s*$", re.M)
STRIP_ITEM = re.compile(r"^(\d+)\. ([a-z0-9-]+)\s*$", re.M)
RUN_LINE = re.compile(r"^\s*-\s*run:\s*(.+?)\s*$", re.M)
ITEM_START = re.compile(r"^(\d+)\. ")


def section(text, heading):
    """The body under this heading, up to the next level-two heading."""
    parts = text.split(heading, 1)
    if len(parts) == 1:
        return ""
    return re.split(r"^## ", parts[1], maxsplit=1, flags=re.M)[0]


def fenced(text):
    """The non-blank lines of the first fenced block in this text."""
    match = re.search(r"```[a-z]*\n(.*?)```", text, re.S)
    if not match:
        return []
    return [
        line.strip() for line in match.group(1).splitlines() if line.strip()
    ]


def project_name(root):
    """The package name this repository currently carries."""
    data = tomllib.loads((root / "pyproject.toml").read_text())
    return data["project"]["name"]


def path_claims(root, text):
    """Backticked tokens that claim a path rooted in a real top-level entry."""
    for token in BACKTICK.findall(text):
        candidate = token.strip().rstrip("/")
        if PATH_UNSAFE.search(candidate) or candidate.startswith("http"):
            continue
        if candidate.startswith("/") or "/" not in candidate:
            continue
        head = candidate.split("/", 1)[0]
        if not (root / head).exists():
            continue
        yield candidate


def table_rows(text):
    """The first cell of every body row of the first table in this text."""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cell = line.strip("|").split("|")[0].strip()
        if not cell or cell == "Feature" or set(cell) <= set("- "):
            continue
        yield cell


def guide_slug(feature):
    """The uninstall guide an interview row names."""
    return ROW_GUIDES.get(feature, feature.lower().replace(" ", "-"))


def numbered_items(text):
    """Split a guide into its numbered items, keeping each item's number."""
    items = []
    current = None
    for line in text.splitlines():
        start = ITEM_START.match(line)
        if start:
            current = [start.group(1), [line]]
            items.append(current)
        elif line.startswith("#"):
            current = None
        elif current is not None:
            current[1].append(line)
    return [(number, "\n".join(lines)) for number, lines in items]


def check_paths(root, findings):
    """Every path the skill, its guides, and the README name must exist."""
    skill = (root / INIT / "SKILL.md").read_text().replace("<skill-dir>", INIT)
    readme = section(
        (root / "README.md").read_text(), "## Start a new project"
    )
    sources = [(f"{INIT}/SKILL.md", skill), ("README.md", readme)]
    for guide in sorted((root / INIT / "uninstalls").glob("*.md")):
        sources.append((f"{INIT}/uninstalls/{guide.name}", guide.read_text()))
    for where, text in sources:
        for claim in sorted(set(path_claims(root, text))):
            if claim in EXPECTED_ABSENT or (root / claim).exists():
                continue
            findings.append(("paths", where, f"{claim} does not exist"))


def check_strip_order(root, findings):
    """Stage 5's order and the uninstalls directory must name each other."""
    skill = (root / INIT / "SKILL.md").read_text()
    ordered = [
        name for _, name in STRIP_ITEM.findall(section(skill, "## Stage 5"))
    ]
    guides = {path.stem for path in (root / INIT / "uninstalls").glob("*.md")}
    where = f"{INIT}/SKILL.md"
    for name in ordered:
        if name not in guides:
            findings.append(
                (
                    "strip-order",
                    where,
                    f"the order names {name}, which has no guide",
                )
            )
    for name in sorted(guides - set(ordered)):
        findings.append(
            (
                "strip-order",
                where,
                f"uninstalls/{name}.md has no slot in the order",
            )
        )
    for name in sorted({n for n in ordered if ordered.count(n) > 1}):
        findings.append(
            ("strip-order", where, f"{name} appears twice in the order")
        )


def check_interview(root, findings):
    """Every interview row maps to a guide, and every guide to a row."""
    skill = (root / INIT / "SKILL.md").read_text()
    rows = list(table_rows(section(skill, "## Stage 1")))
    guides = {path.stem for path in (root / INIT / "uninstalls").glob("*.md")}
    where = f"{INIT}/SKILL.md"
    claimed = set()
    for feature in rows:
        if feature in ROWS_WITHOUT_GUIDES:
            continue
        slug = guide_slug(feature)
        claimed.add(slug)
        if slug not in guides:
            findings.append(
                (
                    "interview",
                    where,
                    f'row "{feature}" has no uninstalls/{slug}.md',
                )
            )
    for name in sorted(guides - claimed):
        findings.append(
            ("interview", where, f"uninstalls/{name}.md has no interview row")
        )


def check_verify_suites(root, findings):
    """Both verify suites must run everything CI runs."""
    name = project_name(root)

    def normalize(command):
        for token in ("<slug>", name):
            command = command.replace(token, "PROJECT")
        return " ".join(command.split())

    ci = (root / CI_WORKFLOW).read_text()
    required = {normalize(line) for line in RUN_LINE.findall(ci)}
    for where in (f"{INIT}/SKILL.md", SYNC_SKILL):
        text = (root / where).read_text()
        suite = {
            normalize(line) for line in fenced(section(text, VERIFY_HEADING))
        }
        for command in sorted(required - suite):
            findings.append(
                (
                    "verify-suite",
                    where,
                    f"CI runs `{command}`; the suite does not",
                )
            )


def check_progress(root, findings):
    """PROGRESS.md's boxes must match SKILL.md's stages one for one."""
    skill = (root / INIT / "SKILL.md").read_text()
    progress = (root / INIT / "PROGRESS.md").read_text()
    stages = STAGE_HEADING.findall(skill)
    boxes = [
        (number, title.split(" (", 1)[0])
        for number, title in PROGRESS_BOX.findall(progress)
    ]
    where = f"{INIT}/PROGRESS.md"
    if len(stages) != len(boxes):
        findings.append(
            ("progress", where, f"{len(boxes)} boxes for {len(stages)} stages")
        )
    for stage, box in zip(stages, boxes):
        if stage != box:
            findings.append(
                (
                    "progress",
                    where,
                    f"box {box[0]}. {box[1]} does not match stage "
                    f"{stage[0]} — {stage[1]}",
                )
            )


def check_symbols(root, warnings):
    """Every symbol a guide item names should still be in the files it names."""
    for guide in sorted((root / INIT / "uninstalls").glob("*.md")):
        where = f"{INIT}/uninstalls/{guide.name}"
        for number, item in numbered_items(guide.read_text()):
            paths = [
                root / claim
                for claim in set(path_claims(root, item))
                if (root / claim).is_file()
                and (root / claim).suffix in SYMBOL_FILE_SUFFIXES
            ]
            if not paths:
                continue
            bodies = [path.read_text() for path in paths]
            named = ", ".join(sorted(str(p.relative_to(root)) for p in paths))
            for token in sorted(set(BACKTICK.findall(item))):
                symbol = token.strip()
                if not IDENTIFIER.match(symbol):
                    continue
                if "_" not in symbol and symbol.islower():
                    continue
                if any(symbol in body for body in bodies):
                    continue
                warnings.append(
                    (
                        "symbols",
                        f"{where} item {number}",
                        f"{symbol} not in {named}",
                    )
                )


def audit(root):
    """Run every check and return its findings and warnings."""
    findings = []
    warnings = []
    check_paths(root, findings)
    check_strip_order(root, findings)
    check_interview(root, findings)
    check_verify_suites(root, findings)
    check_progress(root, findings)
    check_symbols(root, warnings)
    return findings, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    findings, warnings = audit(args.root.resolve())
    for label, rows in (("FINDING", findings), ("WARN", warnings)):
        for check, where, message in rows:
            print(f"{label:8}{check:14}{where}\n{'':22}{message}")
    print(f"\n{len(findings)} findings, {len(warnings)} warnings")
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
