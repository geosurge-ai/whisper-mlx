"""
Full-text search module using BM25.

Provides BM25-based ranking for email and calendar search.
"""

from .bm25 import BM25Scorer, tokenize
from .index import (
    SearchIndex,
    SearchResult,
    SearchResponse,
    create_email_text_extractor,
    create_calendar_text_extractor,
)

__all__ = [
    "BM25Scorer",
    "tokenize",
    "SearchIndex",
    "SearchResult",
    "SearchResponse",
    "create_email_text_extractor",
    "create_calendar_text_extractor",
]
