# The dev stack

Local development is one command — `docker compose up` — and every service in
[`docker-compose.yml`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/docker-compose.yml) runs off the same image, built from
`docker/django/Dockerfile` (see [The Django image](image.md)). The repository
is bind-mounted into every container at `/app`, so an edit on the host is live
in all of them at once; nothing is rebuilt for a code change.

## The services

Three backing stores and four processes:

- **postgres** (postgres 17) — the database, with a named volume so data
  survives restarts.
- **redis** (redis 7) — one instance serving three jobs: Django's cache, the
  celery broker, and the rate-limit counters.
- **elasticsearch** (9.5.1, single node, security off) — the search index,
  also on a named volume. Losing it loses nothing permanent; the index is a
  rebuildable projection of postgres.
- **django** — runs `manage migrate` and then uvicorn with `--reload` against
  `starter.main:application`. Its healthcheck curls `/api/health/` with every
  service named, so `docker compose ps` shows unhealthy when any backing
  store is unreachable, not just when the web process dies.
- **celery** and **celery-beat** — the worker and the scheduler, each its own
  container, mirroring how they deploy.
- **tailwind** and **scripts** — the two watch-mode asset builders:
  `tailwindcss --watch` compiles `starter/app/src/main.css` to
  `static/main.css`, and `manage collectscripts --watch` compiles the
  template `{% script %}` blocks to `static/js/main.js`. Both outputs are
  gitignored build artifacts; if a page loads unstyled or without behaviour,
  one of these two containers is not running.

Each service that talks to a backing store gets its address from an
environment variable, and the settings default every one of them to
localhost so the test suite and ad-hoc commands run against the compose
ports without any configuration:
[`DATABASES`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L164-L173) reads the `POSTGRES_*` variables,
[`REDIS_URL`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L175) points at redis, and
[`ELASTICSEARCH_URL`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/settings.py#L179) at elasticsearch. Compose publishes
each store's port on 127.0.0.1 for exactly that reason.

## Running commands

`uv sync --extra dev` and `source .venv/bin/activate` set up the host
environment. Management commands go through the `manage` console script that
`pyproject.toml` installs — [`manage.main`](https://github.com/nadahlberg/starter/blob/868de346604677e8e70a55e0be811197c2794c35/starter/manage.py#L5-L9)
just sets `DJANGO_SETTINGS_MODULE` and hands `sys.argv` to Django, so
`manage migrate` from anywhere replaces `python manage.py migrate` from a
particular directory.

The django container seeds a login on migrate: with `DEV_USER_EMAIL` and
`DEV_USER_PASSWORD` set (compose defaults them to `dev@example.com` / `dev`),
the `post_migrate` handler creates that account pre-verified and in the
`Developer` group — see [Permissions and groups](../request/permissions.md).
