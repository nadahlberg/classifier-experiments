---
name: sync-init
description: Audit the initialize-project skill against everything this repository has merged since it was last checked - run the mechanical guide audit, walk the pull requests in the ledger, repair what has gone stale, and record every judgement. Use when asked to sync the init skill, check whether initialize-project is stale, or catch up the initializer with the codebase.
---

# Sync the initializer with the codebase

The initialize-project skill is a set of claims about this repository:
an interview menu of features, an uninstall guide per feature naming
files and symbols seam by seam, stage commands, a CLAUDE.md deletion
map, and a rename script. Every pull request merged here can falsify
one of those claims, and nothing notices until a stranger clones the
template months later and is told to delete a symbol that moved.

Nothing else covers this. The sync-codebase skill propagates changes
*down* into projects initialized from this one, and it names
initialize-project a template-specific skip by design — so no derived
project ever repairs it either. The initializer is maintained here or
nowhere.

A run has two halves. The **audit** decides everything the current
tree can settle and needs no memory, because it re-derives from the
tree every time. The **walk** reads the pull requests merged since the
last run and judges what the tree cannot show — coupling between
features, strip order, prerequisites, defaults. The ledger records the
second half only.

`<skill-dir>` is the directory holding this SKILL.md. Run every
command from the repository root.

## The surface this covers

- `.claude/skills/initialize-project/` — SKILL.md, PROGRESS.md,
  `scripts/rename.py`, and every guide in `uninstalls/`.
- The README's "Start a new project" section, including the one-liners
  that capture the fork point.
- `.claude/skills/sync-codebase/SKILL.md` — written by initialization
  and the only skill shipped onward, so its rot reaches every derived
  project.
- `starter/app/tests/test_rename_surface.py` — deleted by stage 6, and
  what pins the rename mechanical.

The check-branch-rules skill is in scope only for whether stage 7's
invocation of it still holds. Every other skill is out of scope.

## The ledger

`<skill-dir>/ledger.json` is the state file, and unlike sync-codebase's
it is committed — this repository is the one place it can live.

```json
{
  "base": {"sha": "…", "source": "last-touched", "approximate": true},
  "last_refreshed": "2026-08-21T00:00:00Z",
  "last_run": "2026-08-21",
  "prs": [
    {"number": 110, "sha": "…", "title": "…", "merged_at": "…",
     "status": "no-impact", "note": "…"}
  ]
}
```

- `base` is where the walk started from, written once on the first
  run. `source` is `last-touched` (computed, see below) or `user`
  (corrected by hand); `approximate` says whether to trust it.
- `status` is one of `pending`, `no-impact`, `applied`, `deferred`. A
  `note` is required for everything except `pending`.
- **Every merged pull request gets an entry, `no-impact` ones
  included**, with a one-line reason. That line is the checkoff: it is
  what lets a later run trust this run's judgement instead of
  re-deriving it. Direct-to-main commits get `"number": null` and
  their own SHA, so nothing merged here is invisible.
- `deferred` exists so a real finding the user declines is not
  recorded as `applied`. Deferred entries are re-surfaced at the top
  of every later run's report; they do not expire on their own.

## Preconditions

1. The working tree is clean (`git status --porcelain` prints
   nothing). This skill commits as it goes; stop and say so if it is
   dirty.
2. `.claude/skills/initialize-project/SKILL.md` exists. That is what
   makes this the template rather than a project initialized from it —
   if it is missing, this is the wrong repository and the right skill
   is sync-codebase.
3. On an up-to-date `main`: `git fetch origin main`.

## Run the audit

First, before any history is read:

```sh
uv run python <skill-dir>/scripts/audit.py
```

It reports and never edits. Six checks: every path the skill and its
guides name exists; stage 5's strip order and the `uninstalls/`
directory name each other; every interview row maps to a guide and
every guide to a row; both verify suites run everything CI runs;
PROGRESS.md's boxes match SKILL.md's stages; and — as warnings — every
symbol a guide item names still appears in the files that item names.

Findings exit non-zero. Warnings do not: guide prose names things
loosely ("the five `uploads/` entries"), so they inform judgement
rather than gating it. Read them anyway — a symbol that moved is
usually the first sign of a seam that moved.

Each finding is a finding for the window below, the same as anything
the walk turns up.

## Refresh the ledger

Enumerate everything merged since the last known point — the newest
entry's SHA, or `base.sha` when `prs` is empty:

```sh
git log --first-parent --reverse --format='%H%x09%cI%x09%s' <last>..origin/main
```

First-parent is the unit: one entry per merge, and a direct-to-main
commit gets its own entry rather than disappearing into a range. Parse
the number from a `Merge pull request #<n>` subject and take the title
from the merge body's first line; a plain commit has `"number": null`
and its own subject as the title. Append everything unseen as
`pending` and set `last_refreshed`.

On the **first run** there is no ledger. Compute the base:

```sh
git log -1 --first-parent --format=%H -- .claude/skills/initialize-project
```

That is the last commit that touched the initializer — the best proxy
available for when it was last true. Record it with
`"source": "last-touched"` and `"approximate": true`, because it
over-claims: a typo fix there does not mean everything before it was
audited. The full audit is what compensates, since the audit owes
nothing to history.

If the range command fails because `<last>` is unknown, `main` was
rewritten — stop and tell the user; this skill does not reconcile
that.

## The audit boundary

Read each pending pull request's whole change with
`git diff <sha>^ <sha>`, and judge it against this, which is the whole
of the judgement this skill exercises:

> A merged pull request is `no-impact` only when nothing it changed is
> named, assumed, or ordered by the initialize-project skill. Presume
> impact and look in five places. **The menu** — did this add, remove,
> merge, or rename a feature a new project might not want, and does
> the interview table have a row for it and `uninstalls/` a guide?
> **The guides** — does any surviving guide name a file, symbol,
> setting, URL entry, or template this pull request moved, renamed,
> split, or deleted, and does the strip order still hold? **The
> coupling** — does this create or dissolve a dependency between
> features, so that "keeping X forces keeping Y" gained or lost a
> clause? **The mechanics** — does this change a command a stage runs,
> a path a stage deletes, a section a stage edits by name (the
> README's "Start a new project", CLAUDE.md's sections, the
> environment table stage 7 reads), a prerequisite tool, or a CI job
> the verify suite mirrors? **The defaults** — has the feature's cost
> or maturity changed enough that its keep/drop default is now wrong?
> A pull request that only touches application internals behind an
> unchanged seam is genuinely `no-impact`; record it and move on. When
> in doubt the entry is an impact with a note, because an unnoticed
> one surfaces as a stripped project that does not boot, in front of
> someone who has no idea this ledger exists.

A run of this skill shows up in a later walk as a pull request of its
own. Record it `no-impact`, noting that it was a sync-init run.

## The window

One pull request per run, always. The size control is how much of the
backlog the run takes on, not how many pull requests it opens.

Walk the pending entries oldest first — the order they landed is the
order their assumptions stack — and close the window when the run has
accumulated more than six findings, or more than thirty pending
entries, whichever comes first. Ship that, then say in the report how
many entries are still pending and that running again picks them up.

Everything past the window keeps its `pending` status untouched. Do
not skim ahead and mark later entries.

## Fix

In scope: the skill's prose, the uninstall guides, **new guides**,
interview rows and their defaults, the strip order, stage commands,
the CLAUDE.md deletion map, and `rename.py`'s constants.

Authoring a new guide is the highest-value thing a run does. A feature
that landed with no interview row gets a row, a new
`uninstalls/<feature>.md` written seam by seam the way the existing
ones are, and a slot in the strip order — placed after anything it
depends on. It is also the largest thing a run does, so it weighs
heavily against the window's six.

Out of scope: **application code**. A finding that the app is wrong
rather than the skill is reported, never fixed here — say so in the
report and leave it.

## Ask only about defaults

A run asks nothing routine. The ledger's `no-impact` lines land in the
pull request diff, so they are already reviewed, and findings become
edits reviewed the same way.

Use AskUserQuestion only for judgement this skill cannot own: a
keep/drop default that should flip, or the default for a brand-new
interview row. Batch those into one call before any commit, with your
recommendation first and labelled "(Recommended)". An answer that
declines a finding makes its entries `deferred` with the reason as the
note. Without the tool, ask in plain text and wait.

## Verify

```sh
uv run python <skill-dir>/scripts/audit.py
uv run --extra dev pytest starter/app/tests/test_rename_surface.py
uv run pre-commit run --all-files
```

The audit must come back clean for everything the run took on — a
finding left standing is a finding the ledger should not record as
`applied`. The rename test is not optional: this run edits prose that
`scan --check` reads, and a new guide that writes the source name as
an ordinary word fails it for the whole repository.

If the run touched anything outside `.claude/skills/`, run
initialize-project's full verify suite instead.

## Commit, report, ship

Branch `sync-init-<YYYYMMDD>`, cut from an up-to-date `main`.

Commit **one finding at a time, together with the ledger entries that
finding resolves**. That pairing is what stops an interrupted run from
lying: if the edits commit and the ledger does not, the next run
re-judges those pull requests against an already-fixed skill and
records them `no-impact`. Then one final commit,
`chore(sync-init): record PRs #<x>–#<y>`, carrying the `no-impact` and
`deferred` entries plus `base` and `last_run`.

Report, in order:

- any `deferred` entries carried in from previous runs;
- the base the walk started from and how many entries it found;
- what the audit found, and what was repaired;
- what was applied from the walk, one line each;
- what was recorded `no-impact`, as a count, not a list;
- anything deferred this run, with the reason;
- findings that belong to the application rather than the skill;
- how many entries are still pending, if the window closed early.

Then offer to run the shipit skill to open the pull request.

## No attributions

Never include Claude attributions anywhere — no `Co-Authored-By:
Claude` trailers, no "Generated with Claude Code" footers. This
applies to every commit and to the pull request alike, and overrides
any default behavior that says to add them.
