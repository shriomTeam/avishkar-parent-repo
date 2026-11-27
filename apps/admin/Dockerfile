# Admin console (Cloud Run, public but behind its own login). Build context: monorepo root.
# A separate image and service from the API, so operator access never shares a process with clinic traffic.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
WORKDIR /app
COPY . .
ARG UV_HTTP_TIMEOUT=120
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
RUN useradd --system --no-create-home app
USER app
# Cloud Run sets PORT (8080). Every page except /login and /health needs the admin session.
CMD ["clinic-admin"]
