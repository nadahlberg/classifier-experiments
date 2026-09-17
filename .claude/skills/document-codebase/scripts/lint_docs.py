"""Check the docs against the symbol index: stale citations and coverage."""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from utils import REFERENCE, build, common_parser


def where(loc):
    """A location as file:start-end, degrading as the span does."""
    rel, start, end = loc
    if start is None:
        return rel
    if end is None or end == start:
        return f"{rel}:{start}"
    return f"{rel}:{start}-{end}"


def cited_text(place):
    """The docs line behind a `path:lineno` citation site, trimmed."""
    path, _, lineno = place.rpartition(":")
    try:
        line = Path(path).read_text().splitlines()[int(lineno) - 1]
    except (OSError, ValueError, IndexError):
        return ""
    return line.strip()[:120]


def edge_owner(label):
    return label.split(" -> ", 1)[0]


def enclosing(label):
    """Names whose `+` could cover this symbol, nearest first.

    Mirrors covered(): an edge's own owner is a candidate, then successive
    `.`/`#` prefixes. A non-edge symbol starts at its first real ancestor,
    never itself.
    """
    owner = edge_owner(label)
    if owner != label:
        yield owner
    while True:
        cut = max(owner.rfind("."), owner.rfind("#"))
        if cut < 0:
            return
        owner = owner[:cut]
        yield owner


def packable(symbols):
    """Label -> id for every symbol a `+` citation could name as a parent."""
    return {
        label: sid
        for sid, (_, label, _, _) in symbols.items()
        if " -> " not in label
    }


def covering(label, by_label):
    for name in enclosing(label):
        sid = by_label.get(name)
        if sid:
            return sid
    return None


def doc_references(docs):
    """Every id cited, plus the subset written with a trailing `+`."""
    cited, packed = defaultdict(list), set()
    if not docs.exists():
        return cited, packed
    for path in sorted(docs.rglob("*.md")):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for match in REFERENCE.finditer(line):
                for item in match.group(1).split(","):
                    sid = item.rstrip("+")
                    cited[sid].append(f"{path}:{lineno}")
                    if item.endswith("+"):
                        packed.add(sid)
    return cited, packed


def covered(symbols, cited, packed):
    """Ids a citation accounts for, expanding each `+` over what it owns.

    A packed citation claims its subtree: nested definitions, a template's
    blocks, and every edge the symbol is the owner of. The parent still needs
    its own sentence -- `+` widens a claim, it does not substitute for one.
    """
    resolved = {sid for sid in cited if sid in symbols}
    parents = {sid: symbols[sid][1] for sid in packed if sid in symbols}
    for sid, (_, label, _, _) in symbols.items():
        if sid in parents:
            continue
        owner = label.split(" -> ", 1)[0]
        for parent in parents.values():
            if owner == parent or owner.startswith(
                (f"{parent}.", f"{parent}#")
            ):
                resolved.add(sid)
                break
    return resolved


def cmd_list(args):
    symbols = build(args.root, args.package, args.docs)
    cited, packed = doc_references(args.docs)
    seen = covered(symbols, cited, packed)
    by_label = packable(symbols)
    for sid, (kind, label, module, loc) in sorted(
        symbols.items(), key=lambda kv: (kv[1][1], kv[1][0])
    ):
        if args.kind and kind != args.kind:
            continue
        if args.module and not module.startswith(args.module):
            continue
        if args.uncovered and sid in seen:
            continue
        line = f"{sid}  {kind:<5}  {label}  |  {where(loc)}"
        owner = covering(label, by_label)
        if owner:
            line += f"  |  covered by sym:{owner}+"
        print(line)


def cmd_lint(args):
    symbols = build(args.root, args.package, args.docs)
    cited, packed = doc_references(args.docs)
    seen = covered(symbols, cited, packed)
    by_identity = {sid[:6]: sid for sid in symbols}

    changed, removed = {}, {}
    for sid, places in cited.items():
        if sid in symbols:
            continue
        current = by_identity.get(sid[:6])
        (changed if current else removed)[sid] = (current, places)

    superseded = {new for new, _ in changed.values()}
    uncovered = {
        sid: v
        for sid, v in symbols.items()
        if sid not in seen and sid not in superseded
    }

    if changed:
        print("CHANGED  (same symbol, different code — re-read and update)")
        for old, (new, places) in sorted(changed.items()):
            kind, label, _, loc = symbols[new]
            print(f"  {label}")
            print(f"    sym:{old} -> sym:{new}   at {where(loc)}")
            for place in places:
                print(f"    cited at {place}")
                text = cited_text(place)
                if text:
                    print(f"      | {text}")
        print()

    if removed:
        print("REMOVED  (referenced in docs, no longer in the code at all)")
        for sid, (_, places) in sorted(removed.items()):
            print(f"  sym:{sid}")
            for place in places:
                print(f"    cited at {place}")
                text = cited_text(place)
                if text:
                    print(f"      | {text}")
        print()

    by_module = defaultdict(int)
    for _, (_, _, module, _) in uncovered.items():
        by_module[module] += 1

    if uncovered:
        print("UNCOVERED BY MODULE  (every one of these still needs a home)")
        ranked = sorted(by_module.items(), key=lambda kv: -kv[1])
        for module, count in ranked[: args.top]:
            print(f"  {count:>4}  {module}")
        if len(ranked) > args.top:
            rest = sum(count for _, count in ranked[args.top :])
            print(f"  {rest:>4}  (+{len(ranked) - args.top} more modules)")
        print()

    total = len(symbols)
    done = total - len(uncovered)
    pct = 100 * done / total if total else 0
    print(
        f"COVERAGE  {done}/{total} ({pct:.0f}%)"
        f"   changed: {len(changed)}   removed: {len(removed)}"
    )
    if args.strict:
        return 1 if (changed or removed or uncovered) else 0
    return 1 if (changed or removed) else 0


def covers(parent, label):
    owner = edge_owner(label)
    return owner == parent or owner.startswith((f"{parent}.", f"{parent}#"))


def cmd_show(args):
    symbols = build(args.root, args.package, args.docs)
    cited, packed = doc_references(args.docs)
    by_label = packable(symbols)
    missing = 0
    for query in args.ids:
        q = query.removeprefix("sym:").rstrip("+")
        sid = q if q in symbols else None
        if sid is None and len(q) >= 6:
            sid = next((s for s in symbols if s[:6] == q[:6]), None)
        if sid is None:
            print(f"{query}: not in the index")
            missing = 1
            continue
        kind, label, module, loc = symbols[sid]
        print(f"sym:{sid}  {kind}  {label}")
        print(f"  at {where(loc)}")
        for name in enclosing(label):
            owner = by_label.get(name)
            if owner:
                print(f"  under sym:{owner}+  {name}")
        children = sorted(
            (v[1], v[0], s)
            for s, v in symbols.items()
            if s != sid and covers(label, v[1])
        )
        if children:
            print(f"  a `+` here also covers {len(children)}:")
            for clabel, ckind, csid in children[: args.limit]:
                print(f"    {csid}  {ckind:<5}  {clabel}")
            if len(children) > args.limit:
                print(f"    (+{len(children) - args.limit} more)")
        stale = {
            c: places
            for c, places in cited.items()
            if c[:6] == sid[:6] and c != sid
        }
        for place in cited.get(sid, []):
            mark = " (packed)" if sid in packed else ""
            print(f"  cited at {place}{mark}")
            text = cited_text(place)
            if text:
                print(f"    | {text}")
        for old, places in sorted(stale.items()):
            for place in places:
                print(f"  STALE citation sym:{old} at {place}")
                text = cited_text(place)
                if text:
                    print(f"    | {text}")
        if sid not in cited and not stale:
            print("  not cited anywhere")
    return missing


def main():
    common = common_parser()

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    lister = sub.add_parser(
        "list", parents=[common], help="print symbols and their ids"
    )
    lister.add_argument(
        "--kind",
        choices=[
            "def",
            "class",
            "var",
            "calls",
            "refs",
            "template",
            "block",
            "extends",
            "includes",
            "uses",
            "renders",
            "file",
        ],
    )
    lister.add_argument("--module", help="only paths under this prefix")
    lister.add_argument("--uncovered", action="store_true")
    lister.set_defaults(func=cmd_list)

    linter = sub.add_parser(
        "lint", parents=[common], help="report stale and uncovered symbols"
    )
    linter.add_argument("--top", type=int, default=15)
    linter.add_argument(
        "--strict",
        action="store_true",
        help="also exit non-zero while anything is still uncovered",
    )
    linter.set_defaults(func=cmd_lint)

    shower = sub.add_parser(
        "show",
        parents=[common],
        help="one symbol's location, owners, subtree, and citations",
    )
    shower.add_argument(
        "ids", nargs="+", help="symbol ids; a stale id resolves by identity"
    )
    shower.add_argument(
        "--limit", type=int, default=20, help="children to list per symbol"
    )
    shower.set_defaults(func=cmd_show)

    args = parser.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
