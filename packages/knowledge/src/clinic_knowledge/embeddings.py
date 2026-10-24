"""Turning text into vectors with Vertex AI. Tests use ``clinic_knowledge.testing.FakeEmbedder`` instead."""

import asyncio
import logging
from typing import Protocol

from clinic_db.models.knowledge import EMBEDDING_DIMENSIONS
from clinic_knowledge.config import KnowledgeSettings
from clinic_knowledge.constants import EMBED_BATCH

log = logging.getLogger("knowledge.embeddings")


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """One vector per text, for passages that will be stored."""

    async def embed_query(self, text: str) -> list[float]:
        """A vector for a question being searched for."""


class VertexEmbedder:
    def __init__(self, settings: KnowledgeSettings):
        self._settings = settings
        self._client = None

    def _client_handle(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=True,
                project=self._settings.gcp_project or None,
                location=self._settings.gcp_location,
            )
        return self._client

    async def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        from google.genai import types

        config = types.EmbedContentConfig(task_type=task, output_dimensionality=EMBEDDING_DIMENSIONS)
        last: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._client_handle().aio.models.embed_content(
                    model=self._settings.embedding_model, contents=texts, config=config
                )
                vectors = [list(e.values) for e in response.embeddings or []]
                if len(vectors) != len(texts) or any(len(v) != EMBEDDING_DIMENSIONS for v in vectors):
                    raise EmbeddingError("The embedding service returned an unexpected answer.")
                return vectors
            except EmbeddingError:
                raise
            except Exception as exc:  # network, quota, 5xx: worth another try
                last = exc
                log.warning("embedding attempt %s failed: %s", attempt + 1, type(exc).__name__)
                await asyncio.sleep(0.5 * 2**attempt)
        raise EmbeddingError("The embedding service is not available right now.") from last

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            vectors.extend(await self._embed(texts[start : start + EMBED_BATCH], "RETRIEVAL_DOCUMENT"))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], "RETRIEVAL_QUERY"))[0]
