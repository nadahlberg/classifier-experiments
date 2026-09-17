# The toolchain

Everything the project pins about its own tooling lives in one
[`pyproject.toml`](sym:5d07e7da3ff6), and `uv` resolves it into
[`uv.lock`](sym:8356d8cb8b84) — the lockfile both the Docker build
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

[`.pre-commit-config.yaml`](sym:e7d14d0fea06) runs ruff (with `--fix`) and
ruff-format plus the standard hygiene hooks, excluding `migrations` and
`references/`. CI runs the identical config through `pre-commit/action`, so
a hook that passes locally cannot fail remotely. One local trap: pre-commit
only sees tracked files, so a brand-new file must be `git add`ed before a
`pre-commit run --all-files` proves anything.

## What is ignored

[`.gitignore`](sym:a5cc29115b83) names the build artifacts alongside the
usual Python noise: the compiled `static/main.css` and `static/js/main.js`,
the downloaded `tailwindcss` binary, and `media/` (dev file storage). All
four are reproducible outputs, so a fresh clone builds them rather than
pulling them. `local/` is scratch space with [its own
`.gitignore`](sym:3df7a7447d50) that ignores everything except itself, so
one-off files never show up in `git status`.
