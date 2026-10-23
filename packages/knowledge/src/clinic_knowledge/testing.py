"""Stand-ins for Google Cloud, for tests and browser tests that must not reach it."""

import hashlib
import math
import re

from clinic_db.models.knowledge import EMBEDDING_DIMENSIONS


class MemoryFileStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, name: str, data: bytes, content_type: str) -> None:
        self.objects[name] = data

    async def get(self, name: str) -> bytes | None:
        return self.objects.get(name)

    async def delete(self, name: str) -> None:
        self.objects.pop(name, None)


def _vector(text: str) -> list[float]:
    """Words are hashed into slots, so texts that share words point the same way (and nothing else is promised)."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % EMBEDDING_DIMENSIONS] += 1.0
    length = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / length for v in vector]


class FakeEmbedder:
    def __init__(self, fail_times: int = 0) -> None:
        self.calls: list[list[str]] = []
        self._fail = fail_times

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self._fail > 0:
            self._fail -= 1
            from clinic_knowledge.embeddings import EmbeddingError

            raise EmbeddingError("The embedding service is not available right now.")
        return [_vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return _vector(text)
