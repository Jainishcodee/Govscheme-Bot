"""ChromaDB-backed vector store for scheme retrieval."""

from __future__ import annotations

import uuid

import chromadb
from chromadb import EmbeddingFunction

from retrieval.embeddings import TfidfEmbeddingFunction
from schema import Scheme


def _doc_text(scheme: Scheme) -> str:
    return f"{scheme.name}. {scheme.description} Benefits: {scheme.benefits}"


def _metadata(scheme: Scheme) -> dict:
    return {
        "category": scheme.category,
        "states": ",".join(scheme.eligibility.state) if scheme.eligibility.state else "",
    }


class SchemeVectorStore:
    def __init__(self, collection, schemes_by_id: dict[str, Scheme]):
        self._collection = collection
        self._schemes_by_id = schemes_by_id

    @classmethod
    def build(
        cls,
        schemes: list[Scheme],
        embedding_fn: EmbeddingFunction | None = None,
        client=None,
        collection_name: str | None = None,
    ) -> "SchemeVectorStore":
        if not schemes:
            raise ValueError("Cannot build a vector store from an empty scheme list.")
        if embedding_fn is None:
            embedding_fn = TfidfEmbeddingFunction.fit([_doc_text(s) for s in schemes])
        if client is None:
            client = chromadb.Client()
        collection_name = collection_name or f"schemes_{uuid.uuid4().hex[:12]}"
        collection = client.create_collection(
            name=collection_name,
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        collection.add(
            documents=[_doc_text(s) for s in schemes],
            ids=[s.scheme_id for s in schemes],
            metadatas=[_metadata(s) for s in schemes],
        )
        return cls(collection, {s.scheme_id: s for s in schemes})

    def query(
        self, query_text: str, top_k: int = 5, category: str | None = None
    ) -> list[tuple[Scheme, float]]:
        n_results = min(top_k, self._collection.count())
        if n_results == 0:
            return []
        where = {"category": category} if category else None
        result = self._collection.query(query_texts=[query_text], n_results=n_results, where=where)
        return [
            (self._schemes_by_id[scheme_id], distance)
            for scheme_id, distance in zip(result["ids"][0], result["distances"][0])
        ]

    @staticmethod
    def filter_by_state(
        results: list[tuple[Scheme, float]], state: str
    ) -> list[tuple[Scheme, float]]:
        normalized_state = state.lower()
        return [
            (scheme, distance)
            for scheme, distance in results
            if not scheme.eligibility.state
            or normalized_state in [item.lower() for item in scheme.eligibility.state]
        ]

    def __len__(self) -> int:
        return self._collection.count()
