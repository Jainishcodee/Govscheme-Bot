"""Offline TF-IDF embeddings used by the ChromaDB scheme index."""

from __future__ import annotations

from scipy.sparse import hstack
from chromadb import Documents, EmbeddingFunction, Embeddings
from sklearn.feature_extraction.text import TfidfVectorizer


class TfidfEmbeddingFunction(EmbeddingFunction):
    """Combine word and character TF-IDF vectors for each document/query."""

    def __init__(self, word_vectorizer: TfidfVectorizer, char_vectorizer: TfidfVectorizer):
        self._word_vectorizer = word_vectorizer
        self._char_vectorizer = char_vectorizer

    @classmethod
    def fit(cls, corpus: list[str]) -> "TfidfEmbeddingFunction":
        word_vectorizer = TfidfVectorizer(
            analyzer="word", ngram_range=(1, 2), stop_words="english", min_df=1
        )
        char_vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), min_df=1
        )
        word_vectorizer.fit(corpus)
        char_vectorizer.fit(corpus)
        return cls(word_vectorizer, char_vectorizer)

    def __call__(self, input: Documents) -> Embeddings:
        texts = list(input)
        word_matrix = self._word_vectorizer.transform(texts)
        char_matrix = self._char_vectorizer.transform(texts)
        return hstack([word_matrix, char_matrix]).toarray().tolist()

    def name(self) -> str:
        return "tfidf_word_char_embedding_function"
