# Transactional email sender (Cloud Run, private, called by Cloud Tasks). Build context: monorepo root.
# A separate image from the API so it can have its own scaling, memory and timeout.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
WORKDIR /app
COPY . .
ARG UV_HTTP_TIMEOUT=120
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
RUN useradd --system --no-create-home app
USER app
# Cloud Run sets PORT (8080). OIDC-authenticated tasks contain only a delivery UUID.
CMD ["python", "-m", "clinic_engagement.email.task_app"]
