# Starter wiki

This wiki explains the starter codebase to someone who has not read it: why
each boundary exists, which of two similar things is the real entry point,
and what breaks when a rule is ignored. It is built from `docs/.src` — edit
there, never the rendered pages.

The app is a Django 5 mono-app (`starter.app`) with a strict split between
business logic (services and selectors) and thin interfaces (views, API
endpoints, tasks, MCP tools, management commands), plus a second service —
an MCP server — mounted beside Django in the same process.

## Running and shipping it

- [Development](development/README.md) — the compose stack, the shared
  Docker image, the toolchain, and how the test suite is wired.
- [Deploy](deploy/README.md) — CI, the Pulumi pipeline, the DigitalOcean
  infrastructure and Kubernetes workloads, secrets, runtime configuration,
  Sentry, and the database-reset escape hatch.
- [Conventions](conventions/README.md) — the machine-enforced house rules:
  the pattern-check machinery and the full rule catalog.

## How things work everywhere

- [The request layer](request/README.md) — routing, errors, API
  authentication, rate limiting, permissions, pagination.
- [Templates](templates/README.md) — placement, layouts, the design-system
  primitives, theming, the script bundle, CSP and Alpine.
- [Caching](mechanisms/caching.md) — keys in one file, lazy selector
  reads, on-commit busting.
- [Background tasks](mechanisms/tasks.md) — celery, thin task interfaces,
  the beat schedule guard.

Pages on storage, search, the MCP server and the agent framework are still
to be written.

## Features

Vertical slices — the demo surfaces, accounts, API tokens, the admin —
each traced through every layer it touches. Still to be written.
