FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/

ENV UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY docker/django/install-tailwind.sh /tmp/install-tailwind.sh
RUN TAILWIND_PATH=/usr/local/bin/tailwindcss sh /tmp/install-tailwind.sh

COPY README.md ./
COPY clx clx
RUN uv sync --frozen
RUN tailwindcss \
    --input clx/app/src/main.css \
    --output clx/app/static/main.css \
    --minify
RUN manage collectscripts

COPY docker/django/entrypoint.sh docker/django/entrypoint.sh

CMD ["sh", "docker/django/entrypoint.sh"]
