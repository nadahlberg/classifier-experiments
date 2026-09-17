# CI

Every push to `main` and every pull request runs [`ci.yml`](sym:899ce9cc2679):
five independent jobs, each a single command against the same lockfile the
image builds from.

- **pre-commit** — the same ruff and hygiene hooks a local commit runs, so
  style cannot pass locally and fail remotely.
- **test** — `uv run --extra dev pytest`, with postgres 17 and
  elasticsearch 9.5.1 as GitHub service containers matching the compose
  versions. Redis is absent on purpose: the suite swaps the cache for an
  in-memory backend on every test (see [Testing](../development/testing.md)),
  and no test talks to a live broker.
- **mypy** — strict type-checking of `starter/`.
- **migrations** — `manage makemigrations --check --dry-run`, which fails
  when a model change was committed without its migration.
- **checks** — `manage check --fail-level WARNING`, the project's own
  pattern checks (see [Pattern checks](../conventions/checks.md)). This is
  the job that enforces the rules CLAUDE.md marks with check ids.

A green run on `main` is what triggers the [deploy
pipeline](pipeline.md) — deploy subscribes to this workflow's completion
rather than to the push itself.
