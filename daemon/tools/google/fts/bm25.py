"""
BM25 Okapi implementation.

Pure Python implementation of the BM25 ranking function for full-text search.
No external dependencies required.

BM25 Formula:
    score(D, Q) = Σ IDF(qi) * (f(qi, D) * (k1 + 1)) / (f(qi, D) + k1 * (1 - b + b * |D|/avgdl))

Where:
    - f(qi, D) = term frequency of qi in document D
    - |D| = document length (in tokens)
    - avgdl = average document length across corpus
    - k1 = term frequency saturation parameter (typically 1.2-2.0)
    - b = length normalization parameter (typically 0.75)
    - IDF(qi) = log((N - n(qi) + 0.5) / (n(qi) + 0.5) + 1)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Sequence


# --- Stopwords ---

# Common English stopwords (minimal set for efficiency)
STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "he", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "to", "was", "were", "will", "with", "you", "your",
    "i", "me", "my", "we", "our", "they", "them", "their", "this",
    "but", "if", "not", "so", "what", "which", "who", "would",
    "have", "had", "do", "does", "did", "been", "being", "can",
    "could", "should", "would", "may", "might", "must", "shall",
})


# --- Tokenizer ---

# Regex to split on non-alphanumeric characters
_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+")


def tokenize(text: str, remove_stopwords: bool = True) -> list[str]:
    """
    Tokenize text into lowercase terms.

    Performs:
    - Lowercasing
    - Split on non-alphanumeric
    - Optional stopword removal
    - Filter tokens < 2 chars

    Args:
        text: Input text to tokenize
        remove_stopwords: Whether to filter out common stopwords

    Returns:
        List of tokens
    """
    if not text:
        return []

    tokens = _TOKEN_PATTERN.findall(text.lower())

    if remove_stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS and len(t) >= 2]
    else:
        tokens = [t for t in tokens if len(t) >= 2]

    return tokens


# --- BM25 Scorer ---


@dataclass
class BM25Scorer:
    """
    BM25 Okapi scorer for document ranking.

    Build the scorer with a corpus of documents, then query to get
    relevance scores for each document.

    Example:
        >>> docs = ["hello world", "hello there", "goodbye world"]
        >>> scorer = BM25Scorer.from_documents(docs)
        >>> scores = scorer.score("hello world")
        >>> # scores[0] will be highest (exact match)
    """

    # Corpus statistics
    doc_count: int
    avg_doc_length: float
    doc_lengths: list[int]

    # Term -> document frequency (how many docs contain term)
    doc_freqs: dict[str, int]

    # Per-document term frequencies: doc_idx -> Counter[term -> freq]
    term_freqs: list[Counter[str]]

    # BM25 parameters
    k1: float = 1.5
    b: float = 0.75

    # Precomputed IDF values
    _idf_cache: dict[str, float] = field(default_factory=dict, repr=False)

    @classmethod
    def from_documents(
        cls,
        documents: Sequence[str],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> BM25Scorer:
        """
        Build a BM25 scorer from a corpus of documents.

        Args:
            documents: List of document texts
            k1: Term frequency saturation (default 1.5)
            b: Length normalization (default 0.75)

        Returns:
            Configured BM25Scorer instance
        """
        doc_count = len(documents)
        if doc_count == 0:
            return cls(
                doc_count=0,
                avg_doc_length=0.0,
                doc_lengths=[],
                doc_freqs={},
                term_freqs=[],
                k1=k1,
                b=b,
            )

        # Tokenize all documents
        tokenized: list[list[str]] = [tokenize(doc) for doc in documents]

        # Compute document lengths
        doc_lengths = [len(tokens) for tokens in tokenized]
        avg_doc_length = sum(doc_lengths) / doc_count

        # Compute term frequencies per document
        term_freqs: list[Counter[str]] = [Counter(tokens) for tokens in tokenized]

        # Compute document frequencies (how many docs contain each term)
        doc_freqs: dict[str, int] = {}
        for tf in term_freqs:
            for term in tf:
                doc_freqs[term] = doc_freqs.get(term, 0) + 1

        return cls(
            doc_count=doc_count,
            avg_doc_length=avg_doc_length,
            doc_lengths=doc_lengths,
            doc_freqs=doc_freqs,
            term_freqs=term_freqs,
            k1=k1,
            b=b,
        )

    def idf(self, term: str) -> float:
        """
        Compute inverse document frequency for a term.

        Uses the BM25 IDF variant:
            IDF = log((N - n + 0.5) / (n + 0.5) + 1)

        where N = total docs, n = docs containing term.
        """
        if term in self._idf_cache:
            return self._idf_cache[term]

        n = self.doc_freqs.get(term, 0)
        idf_val = math.log((self.doc_count - n + 0.5) / (n + 0.5) + 1)
        self._idf_cache[term] = idf_val
        return idf_val

    def score_document(self, query_tokens: list[str], doc_idx: int) -> float:
        """
        Compute BM25 score for a single document against query tokens.

        Args:
            query_tokens: Tokenized query terms
            doc_idx: Index of document in corpus

        Returns:
            BM25 relevance score (higher = more relevant)
        """
        if self.doc_count == 0 or doc_idx >= self.doc_count:
            return 0.0

        doc_len = self.doc_lengths[doc_idx]
        tf_doc = self.term_freqs[doc_idx]

        score = 0.0
        for term in query_tokens:
            if term not in self.doc_freqs:
                continue

            tf = tf_doc.get(term, 0)
            if tf == 0:
                continue

            idf_val = self.idf(term)

            # BM25 term score
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (
                1 - self.b + self.b * doc_len / self.avg_doc_length
            )
            score += idf_val * (numerator / denominator)

        return score

    def score(self, query: str) -> list[float]:
        """
        Score all documents against a query.

        Args:
            query: Query text

        Returns:
            List of scores, one per document (same order as input corpus)
        """
        query_tokens = tokenize(query)
        if not query_tokens:
            return [0.0] * self.doc_count

        return [
            self.score_document(query_tokens, idx)
            for idx in range(self.doc_count)
        ]

    def rank(self, query: str, top_k: int | None = None) -> list[tuple[int, float]]:
        """
        Rank documents by relevance to query.

        Args:
            query: Query text
            top_k: Optional limit on results (None = all)

        Returns:
            List of (doc_idx, score) tuples, sorted by score descending.
            Only includes documents with score > 0.
        """
        scores = self.score(query)

        # Filter to non-zero scores and sort
        ranked = [
            (idx, score)
            for idx, score in enumerate(scores)
            if score > 0
        ]
        ranked.sort(key=lambda x: x[1], reverse=True)

        if top_k is not None:
            ranked = ranked[:top_k]

        return ranked
