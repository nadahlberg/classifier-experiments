# Pattern checks

The architecture rules in [CLAUDE.md](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/CLAUDE.md) that can be
machine-checked are — each one carries a check id like `app.E101`, and
`manage check` fails on a violation, quoting the rule it broke. The rules
themselves are catalogued in [The rule catalog](rules.md); this page is the
machinery that runs them.

## One sweep

[`check_patterns`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/__init__.py#L23-L82) is a single check registered under the
`patterns` tag ([exported](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/__init__.py#L19) alongside the deploy module).
It builds the fact tables once — `codebase_facts()` from
[the codebase selector](../admin/codebase-selector.md) parses every module,
template and route in one pass — then feeds them to every assertion
function. The assertions are pure functions over facts, so a new check is a
function and one line in the sweep, and the whole thing runs without
touching the database (guarded by
[a test](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L847-L858) — system checks run during `migrate` on a fresh
database, where a query would crash before the schema exists).

Every violation goes through [`pattern_error`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/base.py#L11-L18), which
puts the check id in `id` and the CLAUDE.md rule text in `hint` — the error
is the documentation, teaching the rule at the moment it is broken.

## Exemptions that ratchet down

[`EXEMPTIONS`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/base.py#L3) maps check ids to identifiers allowed to
violate them; it ships empty. [`ExemptionLog`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/base.py#L21-L52) records
which entries actually matched during a run, and any entry that matched
nothing becomes [an `app.E801` error of its own](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/base.py#L5-L8) — so the
list can only shrink: a fixed violation forces its exemption to be deleted,
and stale grants never sit around to hide the next violation at the same
identifier.

## The deploy check

[`check_file_serving`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/checks/deploy.py#L10-L23) (`app.E001`) is separate from the
pattern sweep and registered `deploy=True`: `DEBUG=off` with `USE_S3=off`
leaves no process serving static or media files, so every asset would 404.
The image's entrypoint runs `manage check --deploy` before uvicorn, which
makes this the check that stops a misconfigured container from serving at
all; CI runs `manage check --fail-level WARNING` (without `--deploy`, since
CI is not a serving environment).

## The test suite

`test_checks.py` treats the checks as code worth testing on both sides.
[`PATTERN_CASES`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L208-L749) is a table with one entry per check id:
a closure that violates the rule and a clean twin, each built from
[five fact factories](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L120-L139)
that fabricate
[modules from source strings, import edges, routes, template facts and
pattern lists](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L695)
— the template cases reuse
[real template names](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L493)
like `pages/index.html` so the fabricated worlds stay plausible. Each case
[invokes exactly the assertion function it
targets](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L215).

Four parametrized or standalone properties hold over the whole table:
[every check fires on its violation and passes its clean
twin](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L757-L770) — a guard that passes either way has lost its
information; [every message quotes CLAUDE.md in its
hint](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L778-L789); [an exemption silences exactly its
ident and counts as used](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L797-L814); and [a stale exemption
produces E801](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L817-L828). The integration pin is
[the real tree is clean with an empty exemption
map](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L831-L844) — deliberately not marked `django_db`, so a fact
build that starts querying fails this test first.

The deploy check gets the same two-sided treatment through
[`check_ids`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L31-L34): [the bad combination is an
error](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L37-L53), [every other combination
passes](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L60-L73), [the check only runs with
`--deploy`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L76-L90), and — reading the compose file and
entrypoint from [`REPO_ROOT`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L28) — [the web container
actually runs deploy checks before serving](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/app/tests/test_checks.py#L93-L109), so the wiring
that makes the check matter is itself pinned.
