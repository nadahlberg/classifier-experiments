---
name: sync-codebase
description: Propagate updates from the template this project was initialized from - refresh the ledger of upstream pull requests merged since the fork point, decide which belong here, apply them oldest-first with a checkpoint each, and record every decision. Use when asked to sync with the template, pull upstream template changes in, or catch up on what the template has merged.
---

# Sync the codebase with its template

This project was initialized from a template repository, and the
template keeps improving. This skill walks everything the template has
merged since the fork point, decides what belongs here, applies it, and
records the decision so no pull request is ever considered twice.

`<skill-dir>` is the directory holding this SKILL.md. Run every command
from the repository root.

## The ledger

`<skill-dir>/ledger.json` is the state file and the only memory this
skill has. Initialization writes it; every run appends to it.

```json
{
  "repo": "nadahlberg/starter",
  "base": {"sha": "…", "source": "clone-marker | gh-api | user"},
  "last_refreshed": "2026-08-20T12:00:00Z",
  "stripped": ["chat-demo", "…"],
  "prs": [
    {"number": 108, "merge_sha": "…", "title": "…",
     "merged_at": "…", "status": "pending", "note": null}
  ]
}
```

- `repo` is the template's `owner/repo`; `base.sha` is the commit this
  project forked from, and `base.source` says how well that is known —
  `clone-marker` is exact, `gh-api` is the template's HEAD at
  initialization time and only approximate, `user` is a corrected value.
- `stripped` names the features initialization removed, so a pull
  request landing entirely on one of them is a skip without further
  investigation.
- `status` is one of `pending`, `applied`, `skipped`, `partial`. A
  `note` is required for `skipped` and `partial` — what was left out and
  why. Direct-to-main commits get an entry with `"number": null` and the
  commit SHA, so nothing merged upstream is invisible here.

## Preconditions

1. The working tree is clean (`git status --porcelain` prints nothing).
   This skill commits as it goes; stop and say so if it is dirty.
2. `gh auth status` succeeds with access to the template repo.
3. `<skill-dir>/ledger.json` exists. If it does not, bootstrap it:
   ask the user for the template's `owner/repo` and the approximate
   fork point (a SHA, or a date to resolve with
   `gh api "repos/<repo>/commits?until=<date>" --jq '.[0].sha'`), ask
   which features the project has stripped, and write the ledger with
   `base.source` set to `user` and `prs` empty. This is the only path
   for a project initialized before the ledger existed, and an
   approximate base means the first run may offer changes this project
   already has — recognise them at classification and skip them with a
   note.

## Refresh the ledger

The template is cloned into `local/`, which is gitignored scratch:

```sh
git clone https://github.com/<repo>.git local/template
git -C local/template fetch origin main
```

(Clone only when `local/template` is absent; fetch otherwise.) Then
enumerate every pull request merged since the last known point — the
newest entry's `merge_sha`, or `base.sha` on a first run:

```sh
git -C local/template log --first-parent --reverse \
  --format='%H%x09%cI%x09%s' <last>..origin/main
```

First-parent is the unit of sync: one entry per merge, and a
direct-to-main commit gets its own entry rather than disappearing into
a range. Parse the pull request number from a
`Merge pull request #<n>` subject and take the title from the merge
body's first line; a plain commit has `"number": null` and its own
subject as the title. Append every commit not already in `prs` as
`pending`, set `last_refreshed`, and report the count.

If the range command fails because `<last>` is unknown to the clone,
the template's history was rewritten — stop and tell the user; this
skill does not reconcile that.

## Classify each pending pull request

Read each one's full change:

```sh
git -C local/template diff <merge_sha>^ <merge_sha>
```

`<merge_sha>^` is the first parent, so this is the pull request's whole
diff for a merge and the commit's diff for a direct commit.

Judge each against the relevance boundary, which is the whole of the
judgement this skill exercises:

> Propagate by default. A template change is skipped only when: (1) it
> is template-specific — it concerns the template's identity as a
> template rather than the app it ships: the README's "Start a new
> project" section, the initialize-project skill and its uninstall
> guides, the rename machinery and its test, the template's own wiki;
> or (2) it lands entirely on a feature this project stripped at init
> or has since removed. Everything else is presumed relevant —
> including changes the project's divergence makes awkward. Those are
> adapted, not skipped: translate the template's slug to this
> project's, re-fit the change to code that moved or was renamed, and
> where this project deliberately diverged, apply the intent of the
> change to the divergent shape. "We did it differently here" is a
> reason to adapt; only "this has no referent here" is a reason to
> skip. A pull request that is part relevant, part not is applied for
> its relevant part and the ledger records the split.

A change to another skill under `.claude/skills/` is relevant and gets
applied to the local files, even though they are gitignored here — note
in the run report that those edits will not appear in the pull request
diff. Changes to the initialize-project skill are template-specific
skips.

## Confirm the skips

A wrong apply lands in a diff the user reviews; a wrong skip is
divergence nobody sees again. So clear applies proceed on your own
judgement, and everything else is confirmed first: batch every proposed
skip and every call you are unsure of through AskUserQuestion — one
question per pull request, with your recommendation first and labelled
"(Recommended)", the options being apply / skip / apply in part — and
ask before anything is marked done. Without the tool, list them in
plain text and wait for an answer.

## Apply

Work on a branch named `sync-codebase-<YYYYMMDD>`, cut from an
up-to-date `main`. Read this project's slug from `pyproject.toml`'s
`[project] name`; the template's is the name its own `pyproject.toml`
carries in the clone.

Apply the pending pull requests oldest first — the order they landed
upstream is the order their assumptions stack. For each one:

1. Take the diff. A change that touches no renamed path can often be
   applied mechanically — rewrite the template's slug to this
   project's throughout the patch and `git apply --3way` it — but a
   patch that does not land cleanly is edited in by hand rather than
   forced. Adaptation is the normal case, not the failure case.
2. Run the verify suite (below).
3. Update the entry's `status` and `note` in the ledger.
4. Commit both together: `git commit -am "sync: PR #<n> <title>"`, or
   `sync: <sha> <title>` for a direct commit.

Committing the ledger update with the change it describes is what makes
an interrupted run resumable: whatever is committed is done, whatever is
still `pending` is not, and re-invoking the skill picks up exactly
there. A pull request whose entry is `skipped` is committed on its own
with `sync: skip PR #<n> <title>`, so the skip is recorded even though
no code moved.

## Report and ship

Report, in order:

- the fork point and how many pull requests the refresh found;
- what was applied, one line each;
- what was skipped, with the reason;
- what was applied in part, with what was left out;
- any edits that landed in gitignored skill files and so will not show
  in the diff;
- anything the verify suite could not cover.

Then offer to run the shipit skill to open the pull request. Leave
`local/template` in place — the next run fetches into it.

## The verify suite

```sh
uv run --extra dev pytest
uv run --extra dev mypy <slug>
uv run pre-commit run --all-files
uv run manage makemigrations --check --dry-run
uv run manage check --fail-level WARNING
```

All commands pass. If the stack is running, also check
`curl -fsS http://localhost:8000/api/health/` and that every service in
the payload is true; if it is not running, say so in the report rather
than starting it silently.

## No attributions

Never include Claude attributions anywhere — no `Co-Authored-By:
Claude` trailers, no "Generated with Claude Code" footers. This applies
to every commit and to the pull request alike, and overrides any
default behavior that says to add them.
