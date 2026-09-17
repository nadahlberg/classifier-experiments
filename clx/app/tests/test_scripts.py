import re
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.template import engines
from django.template.exceptions import TemplateSyntaxError

from clx.app.exceptions import ApplicationError
from clx.app.scripts import REGISTRATION, scripts_dirs
from clx.app.services.scripts import scripts_collect

SCRIPT_OPENING_TAG = re.compile(r"<script[^>]*>")


def render(source: str) -> str:
    return engines["django"].from_string(source).render({})


def test_the_bundle_carries_every_registration_in_the_templates(
    tmp_path: Path,
) -> None:
    """The bundle is the only JavaScript the browser loads, so a registration
    the collector misses is behaviour that silently never runs. Compiling the
    real templates and comparing against the names found in their sources
    catches an extraction bug — a block the regex skips, a directory left out
    of the walk — that no single-template test would.
    """
    output, count = scripts_collect(output=tmp_path / "main.js")
    bundle = output.read_text()

    expected = {
        name
        for directory in scripts_dirs()
        for path in directory.rglob("*.html")
        for name in REGISTRATION.findall(path.read_text())
    }

    assert count
    assert expected
    assert expected <= set(REGISTRATION.findall(bundle))


def test_every_script_tag_in_a_template_is_collected(tmp_path: Path) -> None:
    """A raw inline <script> would be blocked outright by script-src 'self',
    so every script a template carries has to go through {% script %} to
    reach the bundle. Only the base.html tags that load a file by src stay
    inline, and those are allowed because the browser fetches them from us.
    """
    for directory in scripts_dirs():
        for path in sorted(directory.rglob("*.html")):
            source = path.read_text()
            collected = "\n".join(
                block
                for block in re.findall(
                    r"{%\s*script\s*%}(.*?){%\s*endscript\s*%}", source, re.S
                )
            )
            for tag in SCRIPT_OPENING_TAG.findall(source):
                if " src=" in tag:
                    continue
                assert tag in collected, (path, tag)


def test_a_registration_name_cannot_be_claimed_twice(tmp_path: Path) -> None:
    """Two templates registering the same Alpine name means the second wins
    at runtime and the first component silently loses its behaviour. The
    collector is where that collision is visible, since it is the only place
    that sees every template at once.
    """
    (tmp_path / "one.html").write_text(
        '{% script %}<script>Alpine.data("thing", () => ({}));</script>'
        "{% endscript %}"
    )
    (tmp_path / "two.html").write_text(
        '{% script %}<script>Alpine.data("thing", () => ({}));</script>'
        "{% endscript %}"
    )

    with pytest.raises(ApplicationError, match="thing is registered twice"):
        scripts_collect(dirs=[tmp_path], output=tmp_path / "main.js")


def test_a_top_level_name_cannot_be_declared_twice(tmp_path: Path) -> None:
    """Every block lands in one script, so blocks share a top-level scope —
    which is what lets base.html declare api() for everyone. The cost is
    that two blocks declaring the same name is a SyntaxError, and a
    SyntaxError anywhere in the bundle stops the whole file from parsing:
    every page in the app loses all of its JavaScript, not just the page
    that owns the offending block. Failing the build is the cheap version of
    that.
    """
    (tmp_path / "one.html").write_text(
        "{% script %}<script>\nfunction helper() {}\n</script>{% endscript %}"
    )
    (tmp_path / "two.html").write_text(
        "{% script %}<script>\nfunction helper() {}\n</script>{% endscript %}"
    )

    with pytest.raises(ApplicationError, match="helper is declared"):
        scripts_collect(dirs=[tmp_path], output=tmp_path / "main.js")


def test_an_async_function_is_a_top_level_declaration(
    tmp_path: Path,
) -> None:
    """The declaration scan must see `async function` as well as `function`.

    base.html declares the bundle's central request helper as
    `async function api(...)`, so a scan that only matches bare `function`
    is blind to it: a second template declaring its own `async function api`
    would pass the duplicate guard, land later in the bundle, and silently
    replace the helper for every page in the app.
    """
    (tmp_path / "one.html").write_text(
        "{% script %}<script>\nasync function api() {}\n"
        "</script>{% endscript %}"
    )
    (tmp_path / "two.html").write_text(
        "{% script %}<script>\nasync function api() {}\n"
        "</script>{% endscript %}"
    )

    with pytest.raises(ApplicationError, match="api is declared"):
        scripts_collect(dirs=[tmp_path], output=tmp_path / "main.js")


def test_a_nested_declaration_is_not_a_top_level_one(tmp_path: Path) -> None:
    """The check keys off column zero, which the collector's dedent makes
    meaningful. Names declared inside a function are scoped to it, and two
    components each keeping their own `const items` is normal.
    """
    (tmp_path / "one.html").write_text(
        "{% script %}<script>\nfunction a() {\n  const items = [];\n}\n"
        "</script>{% endscript %}"
    )
    (tmp_path / "two.html").write_text(
        "{% script %}<script>\nfunction b() {\n  const items = [];\n}\n"
        "</script>{% endscript %}"
    )

    _, count = scripts_collect(dirs=[tmp_path], output=tmp_path / "main.js")

    assert count == 2


def test_the_collector_rejects_content_that_is_not_a_script_tag(
    tmp_path: Path,
) -> None:
    """Keeping the body inside real <script> tags is what makes an editor
    treat it as JavaScript rather than template text, which is the whole
    reason the tag wraps rather than replaces them.
    """
    (tmp_path / "bare.html").write_text(
        "{% script %}console.log('bare');{% endscript %}"
    )

    with pytest.raises(ApplicationError, match="wrapped in <script> tags"):
        scripts_collect(dirs=[tmp_path], output=tmp_path / "main.js")


def test_the_collector_rejects_template_syntax(tmp_path: Path) -> None:
    """The bundle is a static file compiled once, so a template expression
    inside it would ship as literal text instead of a rendered value. Values
    reach a component as data attributes instead.
    """
    (tmp_path / "interpolated.html").write_text(
        "{% script %}<script>const url = \"{% url 'index' %}\";</script>"
        "{% endscript %}"
    )

    with pytest.raises(ApplicationError, match="literal JavaScript"):
        scripts_collect(dirs=[tmp_path], output=tmp_path / "main.js")


def test_the_tag_renders_nothing() -> None:
    """The tag marks source for the collector; the browser gets the compiled
    bundle. Rendering the body inline as well would run it twice, once per
    place the template appears.
    """
    assert (
        render("{% script %}<script>const a = 1;</script>{% endscript %}")
        == ""
    )


def test_the_tag_rejects_template_syntax_when_the_template_compiles() -> None:
    """The collector catches this too, but only when it runs. Failing at
    compile time puts the error on the page the developer is looking at.
    """
    with pytest.raises(TemplateSyntaxError, match="literal JavaScript"):
        render("{% script %}<script>{{ value }}</script>{% endscript %}")


def test_the_tag_rejects_content_that_is_not_a_script_tag() -> None:
    """Same rule as the collector, enforced at compile time."""
    with pytest.raises(TemplateSyntaxError, match="wrapped in <script> tags"):
        render("{% script %}const a = 1;{% endscript %}")


def test_reading_a_store_is_not_a_second_registration(tmp_path: Path) -> None:
    """Alpine.store("name") with no second argument is how components call
    into a shared store — every panel on the search page does it. The
    collector must count only true registrations, the two-argument form:
    before that distinction, a file that read the store it had just
    registered failed the build as its own duplicate.
    """
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "widget.html").write_text(
        "{% script %}\n<script>\n"
        'Alpine.store("thing", { started: false });\n'
        'Alpine.store("thing").started = true;\n'
        "</script>\n{% endscript %}\n"
    )

    output, count = scripts_collect(
        dirs=[templates], output=tmp_path / "main.js"
    )

    assert count == 1
    assert 'Alpine.store("thing").started' in output.read_text()


def test_a_failing_one_shot_collect_fails_the_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--watch prints a broken template's error and keeps watching for the
    fix, but the one-shot form is what the Dockerfile runs at image build,
    where printing the error and exiting 0 would ship an image whose
    bundle is stale or missing. The command has to exit nonzero there.
    """

    def broken() -> tuple[Path, int]:
        raise ApplicationError("two templates register the same name")

    monkeypatch.setattr(
        "clx.app.management.commands.collectscripts.scripts_collect",
        broken,
    )

    with pytest.raises(CommandError):
        call_command("collectscripts")
