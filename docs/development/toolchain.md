# The toolchain

Everything the project pins about its own tooling lives in one
[`pyproject.toml`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/pyproject.toml), and `uv` resolves it into
[`uv.lock`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/uv.lock) — the lockfile both the Docker build
(`uv sync --frozen`) and CI (`setup-uv` with caching) install from, so every
environment gets identical versions.

## What pyproject declares

- **Dependencies** in two tiers: runtime under `dependencies`, and a `dev`
  extra holding what only humans and CI run — pytest, mypy and its stubs
  packages, and pulumi (the infra program has its own project, but mypy
  type-checks `infra/` from the root environment).
- **The `manage` console script**, which is why `manage migrate` works from
  any directory once the venv is active.
- **Ruff** as both linter and formatter — line length 79, isort with
  `starter` as first-party, and a curated rule set. `references/` is
  excluded from linting, matching its role as a holding pen that no tool
  touches.
- **Mypy strict**, with the django-stubs plugin pointed at
  `starter.settings`, and `ignore_missing_imports` only for the handful of
  untyped packages (allauth, django-ratelimit, litellm, oauth2_provider).
- **Pytest** configured to ignore `references/` and find the settings module
  itself (`django_find_project = false`), so tests run from the repo root
  with no `manage.py` discovery.

## Pre-commit

[`.pre-commit-config.yaml`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/.pre-commit-config.yaml) runs ruff (with `--fix`) and
ruff-format plus the standard hygiene hooks, excluding `migrations` and
`references/`. CI runs the identical config through `pre-commit/action`, so
a hook that passes locally cannot fail remotely. One local trap: pre-commit
only sees tracked files, so a brand-new file must be `git add`ed before a
`pre-commit run --all-files` proves anything.

## What is ignored

[`.gitignore`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/.gitignore) names the build artifacts alongside the
usual Python noise: the compiled `static/main.css` and `static/js/main.js`,
the downloaded `tailwindcss` binary, and `media/` (dev file storage). All
four are reproducible outputs, so a fresh clone builds them rather than
pulling them. `local/` is scratch space with [its own
`.gitignore`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/local/.gitignore) that ignores everything except itself, so
one-off files never show up in `git status`.
