"""Build <docs> from <docs>/.src, turning sym: citations into GitHub permalinks."""

import argparse
import re
import shutil
import subprocess
import sys

from utils import REFERENCE, build, common_parser

REMOTE = re.compile(
    r"(?:git@github\.com:|https://github\.com/)([^/]+/[^/]+?)(?:\.git)?/?$"
)


def git(repo, *args, strip=True):
    out = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    return out.strip() if strip else out


def github_base(repo):
    url = git(repo, "remote", "get-url", "origin")
    match = REMOTE.match(url)
    if not match:
        sys.exit(f"origin is not a GitHub remote: {url}")
    return f"https://github.com/{match.group(1)}"


def permalink(base, sha, loc):
    path, start, end = loc
    url = f"{base}/blob/{sha}/{path}"
    if start:
        url += f"#L{start}" if not end or end == start else f"#L{start}-L{end}"
    return url


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, parents=[common_parser()]
    )
    args = parser.parse_args()

    docs, src = args.docs, args.docs / ".src"
    if not src.is_dir():
        sys.exit(f"{src} does not exist; write pages there and rerun")

    symbols = build(args.root, args.package, args.docs)
    locations = {sid: loc for sid, (_, _, _, loc) in symbols.items()}
    base = github_base(args.root)
    sha = git(args.root, "rev-parse", "HEAD")

    missing, linked = set(), set()

    def replace(match):
        first = match.group(1).split(",")[0].rstrip("+")
        loc = locations.get(first)
        if loc is None:
            missing.add(f"sym:{match.group(1)}")
            return match.group(0)
        linked.add(loc[0])
        return permalink(base, sha, loc)

    pages = {}
    for path in sorted(src.rglob("*")):
        if path.is_file():
            rel = path.relative_to(src)
            pages[rel] = (
                REFERENCE.sub(replace, path.read_text())
                if path.suffix == ".md"
                else None
            )

    if missing:
        print("UNRESOLVED  (fix with lint, then rebuild; nothing was written)")
        for ref in sorted(missing):
            print(f"  {ref}")
        sys.exit(1)

    for rel, text in pages.items():
        out = docs / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            shutil.copy2(src / rel, out)
        else:
            out.write_text(text)

    written = {docs / rel for rel in pages}
    for path in sorted(docs.rglob("*"), reverse=True):
        if path == src or src in path.parents:
            continue
        if path.is_file() and path not in written:
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()

    dirty = {
        line[3:]
        for line in git(
            args.root, "status", "--porcelain", strip=False
        ).splitlines()
    }
    stale = sorted(linked & dirty)
    if stale:
        print("WARNING  permalinks resolve against HEAD, but these files have")
        print("uncommitted changes — commit them and rebuild:")
        for path in stale:
            print(f"  {path}")

    print(f"BUILT  {len(pages)} files -> {docs}")


if __name__ == "__main__":
    main()
