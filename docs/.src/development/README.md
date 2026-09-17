# Development

Working on the project locally. The [repository README](sym:8ec9a07a22f9)
holds the quickstart commands and the table of deploy secrets; these pages
explain the machinery behind them.

- [The dev stack](stack.md) — what `docker compose up` runs and how the
  services find each other.
- [The Django image](image.md) — the one image every process runs, its
  build layers and entrypoint.
- [The toolchain](toolchain.md) — uv, ruff, mypy, pytest and pre-commit
  configuration, and what is gitignored and why.
- [Testing](testing.md) — how the suite is wired: the fixtures every test
  leans on and the isolation they buy.
