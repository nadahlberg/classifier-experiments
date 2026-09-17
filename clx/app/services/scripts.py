from pathlib import Path

from django.conf import settings

from clx.app.exceptions import ApplicationError
from clx.app.scripts import (
    DECLARATION,
    REGISTRATION,
    scripts_bodies,
    scripts_dirs,
)

BUNDLE = settings.BASE_DIR / "app" / "static" / "js" / "main.js"
HEADER = "/* Compiled by `manage collectscripts`. Do not edit. */"


def scripts_collect(
    *, dirs: list[Path] | None = None, output: Path | None = None
) -> tuple[Path, int]:
    """Compile every script block in the templates into one bundle."""
    output = BUNDLE if output is None else output
    registered: dict[str, str] = {}
    declared: dict[str, str] = {}
    chunks: list[str] = []

    for directory in scripts_dirs() if dirs is None else dirs:
        for path in sorted(directory.rglob("*.html")):
            origin = str(path.relative_to(directory.parent))
            for body in scripts_bodies(path.read_text(), origin=origin):
                for name in REGISTRATION.findall(body):
                    if name in registered:
                        raise ApplicationError(
                            f"{name} is registered twice: "
                            f"{registered[name]} and {origin}"
                        )
                    registered[name] = origin
                for name in DECLARATION.findall(body):
                    if name in declared:
                        raise ApplicationError(
                            f"{name} is declared at the top level twice: "
                            f"{declared[name]} and {origin}"
                        )
                    declared[name] = origin
                chunks.append(f"/* {origin} */\n{body}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n\n".join([HEADER, *chunks]) + "\n")
    return output, len(chunks)
