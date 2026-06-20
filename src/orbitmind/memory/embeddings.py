"""Optional embedding / vector-search boundary — DISABLED by default (ADR-0022).

Phase 3B proves deterministic lexical + PostgreSQL full-text retrieval first. This
module defines the interface so a future phase can add embeddings/pgvector behind an
explicit flag, but the **default implementation is null and disabled**: no network
calls, no model downloads, no API keys, no pgvector requirement. Exact lexical
retrieval is always preserved as the fallback; approximate retrieval is never labelled
exact.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from orbitmind.core.config import Settings


class EmbeddingRecord(BaseModel):
    """A vector for a chunk/text, tagged with its provider + dimensionality."""

    chunk_id: str
    vector: tuple[float, ...]
    dim: int
    provider: str
    provider_version: str


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Produces embeddings. The default provider is disabled."""

    name: str
    enabled: bool

    def embed(self, items: list[tuple[str, str]]) -> list[EmbeddingRecord]:
        """Embed (chunk_id, text) pairs. Disabled providers must raise."""
        ...


@runtime_checkable
class VectorSearchProvider(Protocol):
    """Approximate vector search. The default provider is disabled."""

    name: str
    enabled: bool

    def search(self, vector: tuple[float, ...], k: int) -> list[tuple[str, float]]:
        """Return (chunk_id, distance) pairs. Disabled providers must raise."""
        ...


class NullEmbeddingProvider:
    """Default: embeddings are disabled. No model, no network, no API key."""

    name = "null"
    enabled = False

    def embed(self, items: list[tuple[str, str]]) -> list[EmbeddingRecord]:
        raise RuntimeError(
            "embeddings are disabled by default (ADR-0022); enable a provider explicitly"
        )


class NullVectorSearchProvider:
    """Default: vector search is disabled. Lexical/full-text retrieval is the fallback."""

    name = "null"
    enabled = False

    def search(self, vector: tuple[float, ...], k: int) -> list[tuple[str, float]]:
        raise RuntimeError(
            "vector search is disabled by default (ADR-0022); deterministic lexical / "
            "PostgreSQL full-text retrieval is the supported path"
        )


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Return the configured embedding provider. Default is the null (disabled) one."""
    # No real provider is wired in this phase; embeddings stay disabled regardless of
    # the flag until a provider is added behind an explicit, offline-friendly config.
    _ = settings.memory_embeddings_enabled
    return NullEmbeddingProvider()


def get_vector_search_provider(settings: Settings) -> VectorSearchProvider:
    """Return the configured vector-search provider. Default is null (disabled)."""
    _ = settings.memory_embeddings_enabled
    return NullVectorSearchProvider()
