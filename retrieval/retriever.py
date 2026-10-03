"""Application-facing interface for scheme retrieval."""

from __future__ import annotations

from schema import Scheme
from retrieval.vector_store import SchemeVectorStore


class SchemeRetriever:
    def __init__(self, store: SchemeVectorStore, default_top_k: int = 5):
        self._store = store
        self._default_top_k = default_top_k

    def retrieve(
        self, query_text: str, top_k: int | None = None, category: str | None = None
    ) -> list[Scheme]:
        return [
            scheme
            for scheme, _ in self.retrieve_with_scores(
                query_text, top_k=top_k, category=category
            )
        ]

    def retrieve_with_scores(
        self, query_text: str, top_k: int | None = None, category: str | None = None
    ) -> list[tuple[Scheme, float]]:
        if not query_text or not query_text.strip():
            return []
        return self._store.query(
            query_text,
            top_k=top_k if top_k is not None else self._default_top_k,
            category=category,
        )

    @classmethod
    def from_schemes(cls, schemes: list[Scheme], default_top_k: int = 5) -> "SchemeRetriever":
        return cls(SchemeVectorStore.build(schemes), default_top_k=default_top_k)
