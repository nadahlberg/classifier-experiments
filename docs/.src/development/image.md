# The Django image

One image serves every Python process — web, celery worker, beat, and the
dev asset watchers — so dev and production run the same bytes and a compose
service is just a different command against the same build.

## The build

[`docker/django/Dockerfile`](sym:0047902bc7a3) starts from `python:3.13-slim`
and copies the `uv` binary out of Astral's image rather than pip-installing
it. Setting `UV_PROJECT_ENVIRONMENT=/usr/local` makes `uv sync` install into
the system interpreter — no venv inside the container, so `manage`, `celery`
and `uvicorn` are on `PATH` with no activation step.

The layers are ordered for cache hits: dependencies first
(`uv sync --frozen --no-install-project` against only `pyproject.toml` and
`uv.lock`), then the tailwind binary, then the source, then a second
`uv sync --frozen` to install the project itself. A code change therefore
rebuilds only the last few layers; a dependency change invalidates from the
lockfile down.

Both static artifacts are compiled at build time — `tailwindcss --minify`
for the CSS and `manage collectscripts` for the JS bundle — which is why a
deployed image never needs the `tailwind` or `scripts` watcher services that
dev compose runs. [`install-tailwind.sh`](sym:dc7bd7d7d13f) downloads the
standalone tailwind binary for the current OS and architecture (pinnable via
`TAILWIND_VERSION`, defaulting to latest), so node is never installed
anywhere.

[`.dockerignore`](sym:05a721ff9d33) keeps `local/`, `references/`, `media/`,
`infra/` and the git history out of the build context, so scratch work never
invalidates a layer.

## The entrypoint

The image's default command, [`entrypoint.sh`](sym:e0cd11d4802d), runs
`manage check --deploy` and then execs uvicorn without `--reload`. The check
runs the project's own pattern checks along with Django's deploy checks, so
an image that violates a machine-enforced rule refuses to start rather than
serving. Dev compose overrides the command (adding migration and reload);
production uses it as-is, which is why migrations are a deploy-workflow step
rather than an entrypoint step — multiple replicas racing `migrate` at boot
would be the alternative.
