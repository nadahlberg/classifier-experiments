"""Tests pinning the mechanical renameability of the project identity.

The initialize-project skill renames every occurrence of "starter" with
a context-classifying script rather than a bare find-and-replace, so the
repo must hold the invariant that every occurrence of the word — in any
case — sits in a context the script can claim (a module path, a file
path, a kebab identifier, an env prefix, a quoted value, and so on).
The moment someone writes "starter" as ordinary prose, a rename would
corrupt that sentence, so the scan must fail and force a rewording.

This file is itself excluded from the scan (SKIP_SUFFIXES in the
script): its fixtures deliberately contain both claimable shapes in
positions the source file distorts (a literal "\n" instead of a real
newline) and prose shapes that must stay unclaimable. It never imports
the application package, so it survives the rename untouched; the
skill's finalize stage deletes it along with the script it drives.

That deletion is also why the README test below lives here rather than
in a file of its own: it pins the template's own initialization
surface, which stops existing the moment a project is initialized.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / ".claude/skills/initialize-project/scripts/rename.py"
CLONE_COMMAND = re.compile(r"^gh repo clone .*$", re.M)


def run_rename(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the rename script with the given arguments, capturing output."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_every_starter_occurrence_is_renameable_by_context() -> None:
    """Scanning the real repo finds no occurrence the script cannot claim.

    This is the guard that keeps the rename mechanical forever: it fails
    when a new "starter" lands in prose (or any other unclaimed context)
    anywhere the rename would touch — which is everything except docs/,
    local/, lockfiles, build artifacts, and this file. Reword the prose
    or, if the context is genuinely a new identity shape, teach the
    script's classify() to claim it.
    """
    result = run_rename("scan", "--check", "--root", str(REPO_ROOT))
    assert result.returncode == 0, result.stdout + result.stderr


def test_rename_maps_every_variant_by_context(tmp_path: Path) -> None:
    """Each context maps to the right derived form of the new name.

    One fixture line per claim rule: module paths and package globs take
    the slug, kebab identifiers take the hyphenated slug, the env prefix
    takes the uppercased slug, and title case takes the display name.
    The package directory itself is renamed on disk. A second apply must
    be a no-op, which is what lets the skill resume an interrupted run.
    """
    fixture = tmp_path / "fixture.txt"
    fixture.write_text(
        "from starter.app.models import User\n"
        "import starter.settings\n"
        'include = ["starter*"]\n'
        'name = "starter"\n'
        "POSTGRES_DB: starter\n"
        "command: celery -A starter worker\n"
        'image = f"/starter:{tag}"\n'
        'cluster = "starter-postgres"\n'
        "prefix = STARTER_TOKEN\n"
        'default = "Starter"\n'
        "path = /starter/app/static/main.css\n"
        "mypy starter\n"
        "COPY starter starter\n"
        'starter = ["data/*"]\n'
    )
    package = tmp_path / "starter"
    package.mkdir()
    (package / "module.py").write_text("from starter import settings\n")

    result = run_rename(
        "apply",
        "--slug",
        "court_listener",
        "--display",
        "Court Listener",
        "--root",
        str(tmp_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr

    assert fixture.read_text() == (
        "from court_listener.app.models import User\n"
        "import court_listener.settings\n"
        'include = ["court_listener*"]\n'
        'name = "court_listener"\n'
        "POSTGRES_DB: court_listener\n"
        "command: celery -A court_listener worker\n"
        'image = f"/court_listener:{tag}"\n'
        'cluster = "court-listener-postgres"\n'
        "prefix = COURT_LISTENER_TOKEN\n"
        'default = "Court Listener"\n'
        "path = /court_listener/app/static/main.css\n"
        "mypy court_listener\n"
        "COPY court_listener court_listener\n"
        'court_listener = ["data/*"]\n'
    )
    renamed = tmp_path / "court_listener"
    assert renamed.is_dir()
    assert not package.exists()
    assert (renamed / "module.py").read_text() == (
        "from court_listener import settings\n"
    )

    again = run_rename(
        "apply", "--slug", "court_listener", "--root", str(tmp_path)
    )
    assert again.returncode == 0
    assert "Replaced 0 occurrences in 0 files." in again.stdout


def test_unclaimed_prose_fails_the_scan(tmp_path: Path) -> None:
    """Prose use of the identity fails --check and blocks apply.

    The failure mode being prevented: a bare replace turning a sentence
    like this fixture's into gibberish in someone's fresh project. The
    scan names the file and line so the fix is a reword, and apply
    refuses outright rather than writing a partial rename.
    """
    prose = tmp_path / "notes.md"
    prose.write_text("This starter kit is great.\n")

    check = run_rename("scan", "--check", "--root", str(tmp_path))
    assert check.returncode == 1
    assert "notes.md:1" in check.stdout

    apply_result = run_rename(
        "apply", "--slug", "court_listener", "--root", str(tmp_path)
    )
    assert apply_result.returncode == 2
    assert prose.read_text() == "This starter kit is great.\n"


def test_apply_refuses_a_slug_or_display_containing_the_source(
    tmp_path: Path,
) -> None:
    """A new name containing the old one is refused before anything is written.

    "kickstarter" passes SLUG_PATTERN and a first apply with it would
    succeed — but the skill documents every stage as safe to re-run, and
    a resumed apply would find the source token inside the freshly
    written name and claim it again, turning "from kickstarter.app"
    into "from kickkickstarter.app" across the whole tree, silently.
    The only safe self-overlapping target is a refused one, and the
    display name ("Starter Kit") can overlap exactly like the slug.
    """
    fixture = tmp_path / "fixture.txt"
    fixture.write_text("from starter.app.models import User\n")

    for args in (
        ["--slug", "kickstarter"],
        ["--slug", "clean", "--display", "Starter Kit"],
    ):
        result = run_rename("apply", *args, "--root", str(tmp_path))
        assert result.returncode == 2, result.stdout + result.stderr
        assert fixture.read_text() == "from starter.app.models import User\n"


def test_occurrences_embedded_in_larger_words_stay_unclaimed(
    tmp_path: Path,
) -> None:
    """The identity inside another word is prose, and prose fails the scan.

    Each fixture shape once slipped through classify: an alphanumeric
    neighbor ("Kickstarter.", "NonStarter", "kickstarter_app") or a
    trailing hyphenation ("a non-starter", "self-starter."), all of
    which read as English words that merely contain the identity.
    Claiming any of them would rewrite the middle of a word — the exact
    corruption the scan exists to block — so classify must require a
    non-alphanumeric boundary and never claim a kebab the identity does
    not lead, leaving all five for --check to force a reword.
    """
    prose = tmp_path / "notes.txt"
    prose.write_text(
        "Kickstarter. NonStarter kickstarter_app\n"
        "that idea is a non-starter\n"
        "be a self-starter.\n"
    )

    check = run_rename("scan", "--check", "--root", str(tmp_path))
    assert check.returncode == 1
    assert check.stdout.count("unclaimed:") == 5
    assert "notes.txt:2: that idea is a non-starter" in check.stdout


def test_references_folder_is_pruned_from_the_scan(tmp_path: Path) -> None:
    """Old code under references/ never blocks or suffers the rename.

    An existing-repo initialization moves the previous project into
    references/ wholesale, and that code can hold the identity in any
    context — prose included. The scan must not fail on it (the reword
    rule is for the template's own tree, not the old code), and apply
    must never rewrite it, since it is the reference material a later
    integration reads. Pruning the folder, rather than claiming its
    contents, is what keeps both true.
    """
    refs = tmp_path / "references"
    refs.mkdir()
    old = refs / "notes.md"
    old.write_text("This starter kit is great.\n")

    check = run_rename("scan", "--check", "--root", str(tmp_path))
    assert check.returncode == 0, check.stdout + check.stderr

    applied = run_rename(
        "apply", "--slug", "court_listener", "--root", str(tmp_path)
    )
    assert applied.returncode == 0
    assert old.read_text() == "This starter kit is great.\n"


def test_occurrences_at_file_boundaries_stay_unclaimed(
    tmp_path: Path,
) -> None:
    """A file that ends or begins with the identity is prose, not a claim.

    Python's substring membership makes the empty string a member of
    every string, so the one-character neighbor probes — which read ""
    at a file edge — used to satisfy checks like `nxt in "./*:"` and
    claim "Do not use this starter" (no trailing newline) as a module
    path, turning the fail-closed scan fail-open at exactly the file
    boundaries. The same sentence mid-file was already unclaimed; the
    edges must not behave differently.
    """
    eof = tmp_path / "eof.txt"
    eof.write_text("Do not use this starter")
    bof = tmp_path / "bof.txt"
    bof.write_text('starter" opens this file mid-quote\n')

    check = run_rename("scan", "--check", "--root", str(tmp_path))
    assert check.returncode == 1
    assert check.stdout.count("unclaimed:") == 2


def test_rename_skips_the_sync_ledger_and_the_fork_point_marker(
    tmp_path: Path,
) -> None:
    """The sync skill's state survives the rename byte for byte.

    Both files name the template, not this project: the ledger records
    which repository upstream is and which of its pull requests have
    landed, and `.template-rev` carries the fork point the clone command
    captured. Renaming either would silently repoint the sync skill at a
    repository that does not exist — so the ledger's directory is pruned
    from the walk and the marker is skipped by name. Pruning also means
    the ledger's free prose (a skip note, say) cannot fail --check for
    the whole repo.
    """
    ledger_dir = tmp_path / ".claude/skills/sync-codebase"
    ledger_dir.mkdir(parents=True)
    ledger = ledger_dir / "ledger.json"
    ledger.write_text(
        '{"repo": "nadahlberg/starter", '
        '"prs": [{"note": "this starter change has no referent here"}]}\n'
    )
    marker = tmp_path / ".template-rev"
    marker.write_text("d0ba4a9\nhttps://github.com/nadahlberg/starter.git\n")
    before = ledger.read_text(), marker.read_text()

    check = run_rename("scan", "--check", "--root", str(tmp_path))
    assert check.returncode == 0, check.stdout + check.stderr

    applied = run_rename(
        "apply", "--slug", "court_listener", "--root", str(tmp_path)
    )
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert (ledger.read_text(), marker.read_text()) == before


def test_rename_prunes_the_sync_init_ledger(tmp_path: Path) -> None:
    """The audit ledger survives the rename byte for byte.

    Unlike the sync-codebase ledger, this one is committed in the
    template itself, which puts it inside the scan of the real repo —
    and it is made almost entirely of quoted prose: pull request titles
    and free-form audit notes, written by other people, that routinely
    contain the source name as an ordinary word ("propagate starter
    updates"). Without the prune, every recorded title carrying the word
    would fail --check for the whole repository, and the first person to
    merge such a title would be told to reword someone else's shipped
    pull request. A rename would be worse: it would quietly rewrite the
    audit history into a record of a repository that never existed.
    """
    ledger_dir = tmp_path / ".claude/skills/sync-init"
    ledger_dir.mkdir(parents=True)
    ledger = ledger_dir / "ledger.json"
    ledger.write_text(
        '{"prs": [{"title": "Add a sync-codebase skill: propagate '
        'starter updates into derived projects", "status": "no-impact", '
        '"note": "Starter internals behind an unchanged seam"}]}\n'
    )
    before = ledger.read_text()

    check = run_rename("scan", "--check", "--root", str(tmp_path))
    assert check.returncode == 0, check.stdout + check.stderr

    applied = run_rename(
        "apply", "--slug", "court_listener", "--root", str(tmp_path)
    )
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert ledger.read_text() == before


def test_readme_clone_commands_capture_the_fork_point() -> None:
    """Both start-a-new-project commands record the fork point first.

    The sync skill can only propagate changes from a known base, and the
    only moment that base is knowable is while the clone still has its
    `.git`. Each one-liner therefore writes the HEAD SHA and the origin
    URL into `.template-rev` before it destroys the git directory —
    reorder those and the marker is empty, initialization falls back to
    an approximate base, and every future sync run inherits the guess.
    """
    readme = (REPO_ROOT / "README.md").read_text()
    section = readme.split("## Start a new project", 1)[1]
    commands = CLONE_COMMAND.findall(section)

    assert len(commands) == 2
    for command in commands:
        sha = command.index("rev-parse HEAD > ")
        origin = command.index("remote get-url origin >> ")
        destroy = command.index("rm -rf ")
        assert command.count(".template-rev") == 2
        assert sha < origin < destroy
