# Uninstall infra / Pulumi

Removes the DigitalOcean deploy: the Pulumi program, the deploy and
reset-database workflows, and the cost-estimating skill. Strictly
one-way — the app reads plain env vars and nothing imports from
`infra/` — so no app code changes. `ci.yml` and the Dockerfile stay:
tests still run on every PR and the image builds anywhere.

## Remove

1. The whole `infra/` directory.
2. `.github/workflows/deploy.yml` and
   `.github/workflows/reset-database.yml`.
3. `pyproject.toml`: the `pulumi` dev dependency.
4. `README.md`: the whole "## Environment" section — its secrets
   exist to feed this deploy.
5. `.dockerignore`: the `infra` line.
6. The `.claude/skills/estimate-infra-cost/` directory — it prices
   this deploy and nothing else.

Run the verify suite. (CLAUDE.md's deploy and infra mentions are
handled by the finalize stage's CLAUDE.md pass.)
