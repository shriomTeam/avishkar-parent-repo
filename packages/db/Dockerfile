# Migration image. Build from the repo root:
#   docker build -f packages/db/Dockerfile .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
# The uv workspace needs every member's pyproject.toml; --package installs only clinic-db's dependencies.
COPY . .
RUN uv sync --frozen --no-dev --package clinic-db

WORKDIR /app/packages/db
# Env (set by the Cloud Run job): DATABASE_OWNER_URL, CLINIC_APP_PASSWORD, CLINIC_SYSTEM_PASSWORD, CLINIC_AUTH_PASSWORD
CMD ["sh", "-c", "python -m clinic_db.bootstrap_roles && alembic upgrade head"]
