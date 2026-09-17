# Pattern checks

The architecture rules in [CLAUDE.md](sym:2d5d1060b2fb) that can be
machine-checked are — each one carries a check id like `app.E101`, and
`manage check` fails on a violation, quoting the rule it broke. The rules
themselves are catalogued in [The rule catalog](rules.md); this page is the
machinery that runs them.

## One sweep

[`check_patterns`](sym:6726079b17c8+) is a single check registered under the
`patterns` tag ([exported](sym:27d4eee33bb7) alongside the deploy module).
It builds the fact tables once — `codebase_facts()` from
[the codebase selector](../admin/codebase-selector.md) parses every module,
template and route in one pass — then feeds them to every assertion
function. The assertions are pure functions over facts, so a new check is a
function and one line in the sweep, and the whole thing runs without
touching the database (guarded by
[a test](sym:9ce16eb4324a+) — system checks run during `migrate` on a fresh
database, where a query would crash before the schema exists).

Every violation goes through [`pattern_error`](sym:329753b1af54), which
puts the check id in `id` and the CLAUDE.md rule text in `hint` — the error
is the documentation, teaching the rule at the moment it is broken.

## Exemptions that ratchet down

[`EXEMPTIONS`](sym:2ae3393e07fe) maps check ids to identifiers allowed to
violate them; it ships empty. [`ExemptionLog`](sym:352402afdd92+) records
which entries actually matched during a run, and any entry that matched
nothing becomes [an `app.E801` error of its own](sym:fa64268dc620) — so the
list can only shrink: a fixed violation forces its exemption to be deleted,
and stale grants never sit around to hide the next violation at the same
identifier.

## The deploy check

[`check_file_serving`](sym:c7ffda1d92f0) (`app.E001`) is separate from the
pattern sweep and registered `deploy=True`: `DEBUG=off` with `USE_S3=off`
leaves no process serving static or media files, so every asset would 404.
The image's entrypoint runs `manage check --deploy` before uvicorn, which
makes this the check that stops a misconfigured container from serving at
all; CI runs `manage check --fail-level WARNING` (without `--deploy`, since
CI is not a serving environment).

## The test suite

`test_checks.py` treats the checks as code worth testing on both sides.
[`PATTERN_CASES`](sym:cf795f52c6a6) is a table with one entry per check id:
a closure that violates the rule and a clean twin, each built from
[five fact factories](sym:44f47bc2336f+,c5d90e776dd5,b99622af5b1d,b1b6c519907c,a2ffe526c1e3)
that fabricate
[modules from source strings, import edges, routes, template facts and
pattern lists](sym:8e5adbabad7e,05a3a8d7c40e,d8765b7af1f8,2ab14909047b,2760984c25b1,eacd5a15567f)
— the template cases reuse
[real template names](sym:fb32b42937b1,5a3c9404c5bf,801f1f44cf2d,5ab237f30b5a,a4119681cbcd,3c4c4e274dbe)
like `pages/index.html` so the fabricated worlds stay plausible. Each case
[invokes exactly the assertion function it
targets](sym:f53432f93fed,0ee614a7bdd3,588f8fe82b6e,5761e47e8e09,0d61be5fd4b4,f6330896a865,1bb79edab08e,92e0539e3959,5b9298af5d45,cd3dfd28196c,6dcfca08a4c3,e12d3536d937,e99e6cdd7de4,a50c190b6567,657c2633deec,ff9582bc9695,acda46327770,f8fcf9857bb8,3709f64e40b6,3858fe14846f,cfd51ccefdc4,fb802c7e8411,b20e7f863708,4acc59f7503e,1ac7c043d9a8,eea443305680,983a53a7ca0f,ea4fdc3596de,e77dcd0ced9a,c4f0ee0d9da2,4bc73bd04ab6,47a6217aa880).

Four parametrized or standalone properties hold over the whole table:
[every check fires on its violation and passes its clean
twin](sym:6375e9b7b1ee+) — a guard that passes either way has lost its
information; [every message quotes CLAUDE.md in its
hint](sym:9665465ff04d+); [an exemption silences exactly its
ident and counts as used](sym:1393c51d21ab+); and [a stale exemption
produces E801](sym:b01b36bef0fc+). The integration pin is
[the real tree is clean with an empty exemption
map](sym:46fc66462133+) — deliberately not marked `django_db`, so a fact
build that starts querying fails this test first.

The deploy check gets the same two-sided treatment through
[`check_ids`](sym:5c86e53e0fbb): [the bad combination is an
error](sym:b85d69cfb40a+), [every other combination
passes](sym:ec49a381d908+), [the check only runs with
`--deploy`](sym:ee9182689722+), and — reading the compose file and
entrypoint from [`REPO_ROOT`](sym:08f7aac2225d) — [the web container
actually runs deploy checks before serving](sym:d401d934659d+), so the wiring
that makes the check matter is itself pinned.
