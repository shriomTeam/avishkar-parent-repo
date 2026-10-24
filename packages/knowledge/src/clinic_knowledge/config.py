"""Knowledge base settings, read from the repo-root .env (all optional in dev)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class KnowledgeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore", env_prefix="KNOWLEDGE_")

    # Private bucket for uploaded files (the knowledge-base/ folder). Unset: uploads are refused.
    bucket: str = ""
    # Vertex AI embeddings. The project defaults to the one the app runs in.
    gcp_project: str = ""
    gcp_location: str = "us-central1"
    embedding_model: str = "text-embedding-005"
    # Production ingestion: the API puts a task on this Cloud Tasks queue and Cloud Tasks calls the ingest service at
    # ingest_url, signed as tasks_invoker_email. Unset (local runs, tests): ingestion runs inside the API process.
    tasks_queue: str = ""
    tasks_region: str = ""
    ingest_url: str = ""
    tasks_invoker_email: str = ""
    # The ingest service only accepts calls signed by tasks_invoker_email for this audience (its own address). Unset:
    # allowed outside production only.
    tasks_audience: str = ""
    # Limits per clinic. They keep ingestion cheap and the small database small.
    max_file_bytes: int = 5 * 1024 * 1024
    max_documents: int = 20
    max_chunks: int = 5000


@lru_cache
def get_knowledge_settings() -> KnowledgeSettings:
    return KnowledgeSettings()
