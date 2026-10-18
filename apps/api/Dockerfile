# Build context: monorepo root. Shares the root uv workspace and lockfile.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
RUN useradd --system --no-create-home app
USER app
# Cloud Run sets PORT (8080). Proxy headers are not trusted by uvicorn: the app reads X-Forwarded-For itself
# (TRUSTED_PROXY_HOPS), counting from the right, because the header can be forged.
CMD ["sh", "-c", "exec uvicorn clinic_api.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log --no-proxy-headers"]
