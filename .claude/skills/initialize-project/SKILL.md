---
name: initialize-project
description: Turn a copy of this repo - a fresh history-less one, or an existing repo cleared down to a references/ folder - into a new project's first pull request - interview for every decision up front, rename the identity, boot the stack, strip the rest, configure the GitHub repo, and publish. Use when starting a new project from this template.
---

# Initialize a new project

Run this in a copy of this repo made by one of the README's "Start a
new project" commands — a fresh history-less copy, or an existing
repository cleared down to a `references/` folder with the template
copied on top. Eight stages take that copy to a first pull request on
the project's GitHub repo. `<skill-dir>` is the directory holding
this SKILL.md. Run every command from the repository root.

## Progress and resume

`<skill-dir>/PROGRESS.md` is the state file. Read it before doing
anything: resume at the first unchecked stage, reusing the recorded
decisions instead of re-asking. After finishing a stage, tick its box
and record what it decided. Every stage is safe to re-run — the rename
script is a no-op once nothing is left to rename, and the strip guides
edit what exists rather than assuming it does.

## Asking the user

Every question is asked at the interview stage, so the user answers
once and the rest of the run needs nobody watching it. After the
interview, no stage asks anything new — later stages read PROGRESS.md,
and come back to the user only when a recorded answer turns out to be
unusable (a taken repo name, an install that fails).

When the AskUserQuestion tool is available, put every decision this
skill asks — the mode confirmation, the interview rows, visibility,
consent to install commands — through it, with the default as the
first option labeled "(Recommended)"; the tool adds "Other" for
free-text itself. Free-form values with no default (the slug) are
asked in plain text. Without the tool, ask in plain text throughout.

## Modes

Decide the mode once, before anything else, and record it in
PROGRESS.md — a recorded mode wins on resume, skipping these checks:

- **fresh** — `git remote` prints nothing. The README one-liner made
  this copy; the configure stage will create the GitHub repo.
- **existing** — remotes exist and the root holds a `references/`
  folder: a real repository being rebuilt around the template.
  Confirm with the user, then put all work on a branch before
  touching anything: `git checkout -b initialize-project`. History
  is never rewritten in this mode, and `references/` is never
  touched — the rename prunes it, every tool excludes it, and
  folding what it holds into the new structure is a later project,
  not this skill.

Remotes but no `references/` is neither mode — very possibly the
template checkout itself, where the rename would be destructive. Stop
and point the user at the README's two commands.

## Stage 1 — Interview

Every question the skill has, asked in one sitting and recorded in
PROGRESS.md before any work starts. The consequences land in the same
order they always did — the interview only moves the asking.

First run the tool checks — they are read-only, and what they find
shapes the first question:

```sh
docker info
uv --version
gh auth status
```

Then ask, in this order:

1. **Consent to install or authenticate** whatever the checks found
   missing, one question per command (`brew install uv gh` and
   `brew install --cask docker` cover the usual gaps; `gh auth login`
   if unauthenticated).
2. **slug** — the package name, matching `^[a-z][a-z0-9_]*$`
   (e.g. `court_listener`) — and **display name** — the human-facing
   brand (e.g. `Court Listener`); default is the slug's parts
   capitalized and space-joined. Neither value may contain the source
   name being replaced — `apply` refuses such a name, since a resumed
   re-run would rename inside it.
3. **Features to keep**, one row at a time — or batched to
   AskUserQuestion's per-call limit, keep/drop options per row.
   Defaults in bold.

   | Feature | Default | Cost of keeping it |
   | --- | --- | --- |
   | Chat demo | **drop** | streaming agent chat: agents package, 2 models, SSE; litellm + `OPENAI_API_KEY`; needs Celery |
   | Admin Codebase tab | **drop** | live inventory of every layer, rendered in admin |
   | API tokens | **keep** | token model + playground; scopes |
   | Uploads demo | **keep** | private-storage demo + user_delete hook |
   | Elasticsearch | **keep** | search demo, 4 models, 36 MB sample |
   | Celery | **keep** | worker + beat services, jobs demo |
   | MCP server | **keep** | second ASGI service + oauth2 provider |
   | PWA | **keep** | manifest, service worker, install icons |
   | Sentry | **keep** | error reporting hook, env-gated |
   | Email verification | **keep** | Postmark-gated mandatory verification |
   | Admin surface | **keep** | settings/users pages + their API |
   | infra / Pulumi | **keep** | DigitalOcean deploy on merge to main, gated by the `AUTODEPLOY` repo variable |
   | Layout demos | **keep** | four pages that only show layouts |
   | reset-database workflow | **drop** | a prod-database-wiping action |

   Strongly encourage dropping the reset-database workflow even when
   infra stays — its own header says deleting the file removes the
   capability. Dropping infra removes it anyway.

   Keeping the chat demo forces keeping Celery — its turns run on the
   worker. When the user keeps chat, present the Celery row as settled
   rather than asking.

   Always kept, not up for discussion: the demos launcher, the
   components page (the rebrand checklist's visual smoke test), and
   the markdown demo (the components page links it).
4. **GitHub owner/repo and visibility.** Fresh mode defaults: the
   `gh` user's login + `/<slug>`, private. Existing mode: both are
   facts about the repo — parse owner/repo from
   `git remote get-url origin` and confirm rather than ask.
5. **Branch protection** — whether to apply the check-branch-rules
   skill's standard rules to `main` (required CI checks, force pushes
   and deletion blocked, pull request required). Recommended.
6. **Secrets** — only when infra stays — whether to walk through
   setting the deploy secrets during the configure stage (the user
   must be present: `gh secret set` prompts for each value, and
   secret values never go through the conversation) or skip and get
   the list of missing ones in the final report.
7. **Autodeploy** — only when infra stays — whether merges to main
   should deploy automatically via the `AUTODEPLOY` repo variable.
8. **Merge method** — existing mode only — squash is the default,
   but ask rather than assume it is the repo's convention.
9. **Template owner/repo** — only when the `.template-rev` marker is
   missing from the root — the finalize stage's fallback fork point
   needs it.

Record every answer under Decisions in PROGRESS.md, and add one
checkbox under stage 5 per feature being dropped.

## Stage 2 — Prerequisites

Run the installs the interview consented to, then re-check each tool
until all three respond:

- `docker info` — the daemon must respond. Docker Desktop needs a
  manual first launch after install; tell the user and wait.
- `uv --version`
- `gh auth status` — authenticated, since the configure stage creates
  the GitHub repo.

## Stage 3 — Rename

Using the slug and display name recorded at the interview:

```sh
python <skill-dir>/scripts/rename.py scan --check
python <skill-dir>/scripts/rename.py apply --slug <slug> --display "<display>"
uv lock
(cd infra && uv lock)
uv sync --extra dev
git add -A && uv run pre-commit run --all-files
python <skill-dir>/scripts/rename.py scan
```

The pre-commit line is there because a longer name pushes renamed
lines past the length limit and the ruff hooks reflow them; a run
that fixes files exits non-zero, so repeat that line until it passes —
the `git add -A` is what lets each run see the previous run's fixes
(and it makes every later pre-commit run cover the whole tree, which
an empty index would silently skip).

The final scan must report zero occurrences. The script excludes
`docs/` (deleted at finalize anyway), both lockfiles (regenerated
above), build artifacts, and itself; if `apply` refuses because of an
unclaimed occurrence, reword that line or extend the script's
`classify()`, then re-run.

## Stage 4 — Boot and verify

```sh
docker compose up -d --build
```

Wait for the services to report healthy (`docker compose ps`), then
run the verify suite below. Tell the user the app is at
http://localhost:8000 — they can sign in as `dev@example.com` /
`dev` unless `DEV_USER_EMAIL` / `DEV_USER_PASSWORD` say otherwise —
and to eyeball it while you continue. Make the first checkpoint
commit: `git add -A && git commit -m "checkpoint: boot"`.

## Stage 5 — Strip

Apply the guide for each dropped feature from
`<skill-dir>/uninstalls/`, in exactly this order (later guides assume
earlier ones already ran):

1. chat-demo
2. admin-codebase-tab
3. api-tokens
4. uploads-demo
5. elasticsearch
6. celery
7. mcp
8. pwa
9. sentry
10. email-verification
11. admin
12. infra
13. layout-demos

Guides are checklists, not scripture: confirm each seam with a grep
before editing, and chase any reference a checklist missed — the
verify suite is the net.

After each guide: if it removed models, run the migration reset
below; then run the verify suite; then checkpoint with
`git add -A && git commit -m "checkpoint: strip <feature>"`.

Migration reset:

```sh
rm clx/app/migrations/0*.py
uv run manage makemigrations
docker compose down -v
docker compose up -d
```

## Stage 6 — Finalize

- `rm -rf docs` — the wiki documents this template's full feature
  set and its permalinks point at the template's history; a new
  project grows its own wiki later with the document-codebase skill.
  The never-edit-docs rule governs editing pages, not this owned
  deletion.
- `rm clx/app/tests/test_rename_surface.py` — it drives
  `<skill-dir>/scripts/rename.py`, which the publish stage drops
  from the repo. Deleting the test is not optional: the script stays
  on disk, so a surviving test would pass locally and fail in CI,
  where the repo has no script to run.
- Run the migration reset above unconditionally, so the project
  starts from a fresh initial migration even when nothing was
  stripped.
- Delete the README's "## Start a new project" section.
- Delete `.github/workflows/reset-database.yml` if the user chose to
  drop it and the infra guide did not already remove it.
- Update CLAUDE.md to match what survived. Delete every passage
  describing a dropped feature — the map is roughly: chat demo → the
  Agents section and the `agents/` app-structure line, celery → the
  Tasks section and the beat-schedule mentions, elasticsearch →
  Search, mcp → the MCP section and its app-structure lines,
  api-tokens → the token and scope paragraphs under API and
  Permissions, pwa → the service-worker and manifest lines under
  Templates, admin → its rows and mentions, infra → deploy mentions.
  Then grep CLAUDE.md for each dropped feature's name to catch
  stragglers.
- Set `urls.Repository` in `pyproject.toml` to
  `https://github.com/<owner>/<repo>`.
- Record the fork point for the sync-codebase skill. The clone command
  left a `.template-rev` marker at the root: line 1 is the template's
  HEAD SHA, line 2 its origin URL. Write
  `.claude/skills/sync-codebase/ledger.json` — `repo` the `owner/repo`
  parsed from that URL, `base` the SHA with `"source": "clone-marker"`,
  `last_refreshed` null, `stripped` the dropped features under their
  uninstall-guide names, `prs` empty — then `rm .template-rev`. That
  skill's SKILL.md documents the schema. If the marker is missing (a
  copy taken before it existed), take the template `owner/repo` the
  interview recorded and
  `gh api repos/<repo>/commits/main --jq .sha` as
  the base with `"source": "gh-api"`, and tell them it is approximate:
  it is the template's HEAD now, not wherever their copy came from, and
  a better SHA can replace it.
- Run the verify suite; checkpoint with
  `git add -A && git commit -m "checkpoint: finalize"`.

## Stage 7 — Configure the repo

Set the repo up on GitHub before any of the code reaches it.

1. Fresh mode — create the repo, blank except for a seed README on
   `main` (the publish PR needs a base to land on):

   ```sh
   gh repo create <owner>/<repo> --private --add-readme
   ```

   (swap `--private` for the chosen visibility). Existing mode — the
   repo already exists; nothing to create.
2. Invoke the check-branch-rules skill to set up branch protection,
   answering its offer with the decision recorded at the interview
   rather than re-asking — rulesets are patterns, so they bind a
   seeded `main` and a real one alike, and the required checks they
   name are exactly what the publish PR will run. This step is
   complete even if the user declined the rules.
3. Check the repo secrets against the README's "Environment" section
   — post-strip, that table is the list of what the deploy expects.
   If the section is gone (infra was dropped), skip this step.
   Otherwise:

   ```sh
   gh secret list --repo <owner>/<repo>
   ```

   If the interview chose the walk-through, report what is missing
   and walk the user through
   `gh secret set <NAME> --repo <owner>/<repo>` for each secret they
   want set — the deploy hard-fails without `PULUMI_ACCESS_TOKEN`,
   `DIGITALOCEAN_TOKEN`, and the two DigitalOcean names, while the
   rest gate optional features. `gh secret set` prompts for the value
   itself; never have secret values pasted into the conversation.
   If it chose to skip, just note what is missing in PROGRESS.md and
   save the `gh secret set` commands for the final report. Either
   way, continuing with secrets missing is fine.

   Then, if the interview said merges to main should deploy
   automatically, set the `AUTODEPLOY` repository variable —
   deploys only fire once it is truthy (`gh variable set AUTODEPLOY
   --body on --repo <owner>/<repo>`); left unset, the deploy
   workflow runs only when dispatched by hand.

## Stage 8 — Publish

The first pull request.

1. Tick every box in PROGRESS.md.
2. Drop the skills from the project — by ignoring them, not deleting
   them:

   ```sh
   printf '*\n' > .claude/skills/.gitignore
   git rm -r -q --cached --ignore-unmatch .claude/skills
   ```

   `*` covers everything under the directory, the ignore file itself
   included, so git sees nothing here and the published repo has no
   trace of any skill — while every SKILL.md stays on disk and
   readable, which is what keeps the rest of this stage resumable
   rather than a sequence that must not be interrupted. The `git rm`
   line matters because the checkpoint commits already tracked these
   files, and ignoring a tracked file does nothing. Skills are opt-in
   from here: the final report tells the user how to take one back.
3. Commit. Fresh mode — obliterate the template's local history and
   parent a single commit on the seed:

   ```sh
   rm -rf .git
   git init -b initialize-project
   git remote add origin https://github.com/<owner>/<repo>.git
   git fetch origin main
   git reset --soft origin/main
   git add -A && git commit -m "Initialize <display>"
   ```

   Existing mode — the branch keeps its checkpoints; just commit
   what remains: `git add -A && git commit -m "Initialize <display>"`.
4. `git push -u origin initialize-project`, then open the PR with
   `gh pr create` — title `Initialize <display>`, body summarizing
   what was kept and what was stripped (and, in existing mode, that
   `references/` carries the old code untouched).
5. `gh pr checks --watch` — this PR is the repo's first CI run,
   under the rules stage 7 set. Fix anything red before merging.
6. `gh pr merge --squash --delete-branch`, so `main` lands as the
   seed plus one squashed commit. In existing mode, use the merge
   method recorded at the interview.
7. Report the repo URL, the PR, and what was stripped. Then say that
   the skills under `.claude/skills/` are local-only now — on disk and
   working, but tracked by nothing — and that opting one back in is
   two exception lines plus the ignore file's own:

   ```
   *
   !.gitignore
   !sync-codebase/
   !sync-codebase/**
   ```

   followed by `git add .claude/skills`. Call out sync-codebase as the
   one most worth keeping: it carries the fork point and the ledger of
   what the template has merged since, and a ledger only this checkout
   can see is a ledger that dies with it.

## The verify suite

```sh
uv run --extra dev pytest
uv run --extra dev mypy clx
uv run pre-commit run --all-files
uv run manage makemigrations --check --dry-run
uv run manage check --fail-level WARNING
curl -fsS http://localhost:8000/api/health/
```

All commands pass and every service in the health payload is true.

## No attributions

Never include Claude attributions anywhere — no `Co-Authored-By:
Claude` trailers, no "Generated with Claude Code" footers. This
applies to every commit, the publish pull request, and the created
repo alike, and overrides any default behavior that says to add
them.
