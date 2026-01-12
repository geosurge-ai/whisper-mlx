"""
Generic search index for document collections.

Provides a lazy-loading, generic index that wraps BM25 scoring
for any document type with configurable text extraction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Generic, TypeVar

from .bm25 import BM25Scorer

logger = logging.getLogger("qwen.tools.fts")


T = TypeVar("T")


@dataclass
class SearchResult(Generic[T]):
    """
    A single search result with document and relevance score.
    """
    document: T
    score: float
    rank: int


@dataclass
class SearchResponse(Generic[T]):
    """
    Complete search response with results and metadata.
    """
    query: str
    total_matches: int
    results: list[SearchResult[T]]
    index_size: int
    index_built_at: datetime | None


class SearchIndex(Generic[T]):
    """
    Generic search index for BM25-based full-text search.

    Type parameter T is the document type (e.g., dict for emails/events).

    Features:
    - Lazy index building on first query
    - Configurable text extraction from documents
    - In-memory caching with manual invalidation
    - Returns complete documents with scores

    Example:
        >>> def load_emails() -> list[dict]:
        ...     return [{"subject": "Hello", "body": "World"}, ...]
        >>>
        >>> def extract_text(email: dict) -> str:
        ...     return f"{email['subject']} {email['body']}"
        >>>
        >>> index = SearchIndex(load_emails, extract_text)
        >>> results = index.search("hello world", limit=10)
    """

    def __init__(
        self,
        loader: Callable[[], list[T]],
        text_extractor: Callable[[T], str],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        """
        Create a search index.

        Args:
            loader: Function that loads all documents to index
            text_extractor: Function that extracts searchable text from a document
            k1: BM25 term frequency saturation parameter
            b: BM25 length normalization parameter
        """
        self._loader = loader
        self._text_extractor = text_extractor
        self._k1 = k1
        self._b = b

        # Cached state
        self._documents: list[T] | None = None
        self._scorer: BM25Scorer | None = None
        self._built_at: datetime | None = None

    @property
    def is_built(self) -> bool:
        """Check if index has been built."""
        return self._scorer is not None

    @property
    def size(self) -> int:
        """Number of documents in index (0 if not built)."""
        return len(self._documents) if self._documents else 0

    @property
    def built_at(self) -> datetime | None:
        """When the index was last built."""
        return self._built_at

    def invalidate(self) -> None:
        """
        Invalidate the cached index.

        Call this when underlying data changes to force rebuild on next query.
        """
        self._documents = None
        self._scorer = None
        self._built_at = None
        logger.debug("Search index invalidated")

    def build(self) -> None:
        """
        Build or rebuild the index.

        Loads all documents and constructs the BM25 scorer.
        Usually called automatically on first search.
        """
        logger.info("Building search index...")

        # Load documents
        self._documents = self._loader()

        if not self._documents:
            logger.warning("No documents to index")
            self._scorer = BM25Scorer.from_documents([], k1=self._k1, b=self._b)
            self._built_at = datetime.utcnow()
            return

        # Extract text from each document
        texts = [self._text_extractor(doc) for doc in self._documents]

        # Build scorer
        self._scorer = BM25Scorer.from_documents(texts, k1=self._k1, b=self._b)
        self._built_at = datetime.utcnow()

        logger.info(f"Search index built: {len(self._documents)} documents indexed")

    def _ensure_built(self) -> None:
        """Ensure index is built (lazy initialization)."""
        if not self.is_built:
            self.build()

    def search(
        self,
        query: str,
        limit: int | None = None,
        filter_fn: Callable[[T], bool] | None = None,
    ) -> SearchResponse[T]:
        """
        Search documents by query.

        Args:
            query: Search query text
            limit: Maximum results to return (None = all matches)
            filter_fn: Optional filter applied to results after ranking

        Returns:
            SearchResponse with ranked results and metadata
        """
        self._ensure_built()

        assert self._scorer is not None
        assert self._documents is not None

        # Get ranked document indices
        ranked = self._scorer.rank(query, top_k=None)  # Get all, filter later

        results: list[SearchResult[T]] = []
        rank = 0

        for doc_idx, score in ranked:
            doc = self._documents[doc_idx]

            # Apply filter if provided
            if filter_fn is not None and not filter_fn(doc):
                continue

            rank += 1
            results.append(SearchResult(document=doc, score=score, rank=rank))

            # Check limit after filtering
            if limit is not None and len(results) >= limit:
                break

        return SearchResponse(
            query=query,
            total_matches=len(ranked),
            results=results,
            index_size=self.size,
            index_built_at=self._built_at,
        )


# --- Index Factory Helpers ---


def create_email_text_extractor() -> Callable[[dict[str, Any]], str]:
    """
    Create a text extractor for email documents.

    Extracts: subject, body, snippet, from, to
    """
    def extract(email: dict[str, Any]) -> str:
        parts = [
            email.get("subject", ""),
            email.get("body", ""),
            email.get("snippet", ""),
            email.get("from", ""),
            email.get("to", ""),
        ]
        return " ".join(p for p in parts if p)

    return extract


def create_calendar_text_extractor() -> Callable[[dict[str, Any]], str]:
    """
    Create a text extractor for calendar event documents.

    Extracts: summary, description, location, attendee names/emails
    """
    def extract(event: dict[str, Any]) -> str:
        parts = [
            event.get("summary", ""),
            event.get("description", ""),
            event.get("location", ""),
        ]

        # Add attendee info
        for attendee in event.get("attendees", []):
            if isinstance(attendee, dict):
                parts.append(attendee.get("email", ""))
                parts.append(attendee.get("display_name", ""))

        # Add organizer info
        organizer = event.get("organizer", {})
        if isinstance(organizer, dict):
            parts.append(organizer.get("email", ""))
            parts.append(organizer.get("display_name", ""))

        return " ".join(p for p in parts if p)

    return extract
