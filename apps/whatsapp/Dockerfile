# WhatsApp agent (Cloud Run, public: Meta calls the webhook). Build context: monorepo root.
# A separate image and service from the API, so patient chat traffic never slows the clinic's own traffic.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
WORKDIR /app
COPY . .
ARG UV_HTTP_TIMEOUT=120
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
RUN useradd --system --no-create-home app
USER app
# Cloud Run sets PORT (8080). Serves GET and POST /whatsapp/webhook; every POST is checked against Meta's signature.
CMD ["python", "-m", "clinic_voice_receptionist.whatsapp.service_app"]
