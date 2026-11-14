"""Semantic Memory Engine — Targeted Vector Store for Precedent and Context Retrieval.

Used for:
- Historical decision precedent similarity search
- Similar disruption episode retrieval
- Relevant corporate policy and constraint lookup
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.common.ids import uuid7


@dataclass
class VectorDocument:
    """Indexed semantic document with embedding vector."""

    doc_id: str
    workspace_id: str
    tenant_id: str
    doc_type: str  # policy | incident | decision_precedent
    title: str
    content: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "workspace_id": self.workspace_id,
            "tenant_id": self.tenant_id,
            "doc_type": self.doc_type,
            "title": self.title,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Pure-Python cosine similarity between two vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def _simple_text_embedding(text: str, dim: int = 2048) -> list[float]:
    """Create a repeatable sparse lexical vector for local fallback retrieval.

    This is intentionally not represented as a learned semantic embedding. Stable
    BLAKE2 feature hashing avoids Python's process-randomized hash seed, and the
    larger vector space reduces accidental collisions between unrelated terms.
    Production-grade semantic retrieval should use a configured embedding model.
    """
    if dim < 1:
        raise ValueError("Embedding dimension must be positive")

    vec = [0.0] * dim
    words = re.findall(r"[a-z0-9]+", text.casefold())
    for word in words:
        digest = hashlib.blake2b(
            word.encode("utf-8"),
            digest_size=8,
            person=b"cortex-sem",
        ).digest()
        index = int.from_bytes(digest, byteorder="big", signed=False) % dim
        vec[index] += 1.0

    # L2 normalization keeps document length from dominating cosine similarity.
    norm = math.sqrt(sum(value * value for value in vec))
    if norm > 0.0:
        vec = [value / norm for value in vec]
    return vec


class SemanticMemoryEngine:
    """Targeted semantic vector store for operational context and precedent search."""

    def __init__(self, embedding_dim: int = 2048) -> None:
        self.embedding_dim = embedding_dim
        self._documents: dict[str, VectorDocument] = {}

    def index_document(
        self,
        workspace_id: str,
        tenant_id: str,
        doc_type: str,
        title: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        custom_embedding: list[float] | None = None,
    ) -> VectorDocument:
        """Embed and index a document in semantic memory."""
        doc_id = str(uuid7())
        emb = custom_embedding or _simple_text_embedding(
            f"{title} {content}", dim=self.embedding_dim
        )

        doc = VectorDocument(
            doc_id=doc_id,
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            doc_type=doc_type,
            title=title,
            content=content,
            embedding=emb,
            metadata=metadata or {},
        )
        self._documents[doc_id] = doc
        return doc

    def search_similar(
        self,
        query: str,
        workspace_id: str,
        doc_type: str | None = None,
        limit: int = 5,
        min_similarity: float = 0.3,
        tenant_id: str | None = None,
    ) -> list[tuple[float, VectorDocument]]:
        """Find most semantically similar documents to the query."""
        query_emb = _simple_text_embedding(query, dim=self.embedding_dim)
        scored: list[tuple[float, VectorDocument]] = []

        for doc in self._documents.values():
            if doc.workspace_id != workspace_id:
                continue
            if tenant_id is not None and doc.tenant_id != tenant_id:
                continue
            if doc_type and doc.doc_type != doc_type:
                continue

            sim = _cosine_similarity(query_emb, doc.embedding)
            if sim >= min_similarity:
                scored.append((sim, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:limit]


_global_semantic_mem = SemanticMemoryEngine()


def get_semantic_memory() -> SemanticMemoryEngine:
    return _global_semantic_mem
