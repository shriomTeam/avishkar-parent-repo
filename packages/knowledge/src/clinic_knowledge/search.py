"""Finding the passages that answer a question: vector similarity and keyword match, merged by reciprocal rank fusion.

One SQL statement does both searches, so a lookup costs one query plus one (cached) embedding call. It runs in the
caller's tenant session, so row-level security keeps it inside that clinic; the tenant is never a parameter here.
Passages are reference text from files a clinic uploaded: callers must present them as information, never as
instructions.
"""

import re
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_knowledge.embeddings import Embedder

POOL = 20  # candidates taken from each of the two searches
RRF_K = 60  # the usual constant: it keeps one top rank from drowning out the other search
# A passage must be this similar to the question, or match its words and be at least a little similar. Measured with
# text-embedding-005: passages that answer a question scored 0.60 to 0.77, unrelated ones up to 0.56. Phase 4 tunes
# these against a set of real questions.
MIN_SIMILARITY = 0.58
MIN_SIMILARITY_WITH_KEYWORDS = 0.45
MAX_QUERY_CHARS = 500

STOPWORDS = frozenset(
    "a an and are as at be but by can could do does for from had has have how i if in is it its me my of on or our "
    "so that the their there they this to us was we what when where which who why will with would you your".split()
)

CACHE_SIZE, CACHE_SECONDS = 256, 600.0
_cache: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()

SQL = text(
    """
    WITH q AS (SELECT CAST(:vec AS halfvec(768)) AS v, to_tsquery('simple', :tsq) AS t),
    vec AS (
      SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> q.v) AS rank
      FROM (SELECT id, embedding FROM knowledge.chunks, q ORDER BY embedding <=> q.v LIMIT :pool) c, q
    ),
    kw AS (
      SELECT c.id, row_number() OVER (ORDER BY c.score DESC) AS rank
      FROM (
        SELECT id, ts_rank_cd(tsv, q.t) AS score FROM knowledge.chunks, q
        WHERE tsv @@ q.t ORDER BY score DESC LIMIT :pool
      ) c
    )
    SELECT c.document_id, d.filename, c.heading, c.text, c.text_hash,
           1 - (c.embedding <=> q.v) AS similarity, vec.rank AS vec_rank, kw.rank AS kw_rank
    FROM knowledge.chunks c
    JOIN knowledge.documents d ON d.id = c.document_id
    CROSS JOIN q
    LEFT JOIN vec ON vec.id = c.id
    LEFT JOIN kw ON kw.id = c.id
    WHERE vec.id IS NOT NULL OR kw.id IS NOT NULL
    """
)


@dataclass(frozen=True)
class Hit:
    document_id: uuid.UUID
    filename: str
    heading: str | None
    text: str
    similarity: float  # 0 to 1, cosine
    score: float  # fused rank score, only meaningful for ordering


def keywords(query: str) -> list[str]:
    words = dict.fromkeys(w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2 and w not in STOPWORDS)
    return list(words)[:12]


async def _embed_query(embedder: Embedder, query: str) -> list[float]:
    key, now = " ".join(query.lower().split()), time.monotonic()
    cached = _cache.get(key)
    if cached and now - cached[0] < CACHE_SECONDS:
        _cache.move_to_end(key)
        return cached[1]
    vector = await embedder.embed_query(query)
    _cache[key] = (now, vector)
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return vector


async def search(session: AsyncSession, query: str, *, embedder: Embedder, limit: int = 4) -> list[Hit]:
    """The best passages for ``query``, most relevant first. An empty list means nothing relevant was found."""
    query = " ".join(query.split())[:MAX_QUERY_CHARS]
    if not query:
        return []
    vector = await _embed_query(embedder, query)
    words = keywords(query)
    rows = (
        await session.execute(
            SQL,
            {
                "vec": "[" + ",".join(f"{x:.6f}" for x in vector) + "]",
                # Words are letters and digits only, so they cannot change the meaning of the tsquery.
                "tsq": " | ".join(words) if words else "xqzxqzxqz",
                "pool": POOL,
            },
        )
    ).all()
    scored = []
    for r in rows:
        keyword_hit = r.kw_rank is not None
        if r.similarity < (MIN_SIMILARITY_WITH_KEYWORDS if keyword_hit else MIN_SIMILARITY):
            continue
        score = (1 / (RRF_K + r.vec_rank) if r.vec_rank else 0) + (1 / (RRF_K + r.kw_rank) if keyword_hit else 0)
        scored.append((score, r))
    hits, seen = [], set()
    for score, r in sorted(scored, key=lambda s: s[0], reverse=True):
        if r.text_hash in seen:  # the same passage kept in two documents is told once
            continue
        seen.add(r.text_hash)
        hits.append(Hit(r.document_id, r.filename, r.heading, r.text, float(r.similarity), score))
        if len(hits) == limit:
            break
    return hits
