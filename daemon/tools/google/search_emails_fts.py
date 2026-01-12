"""
Full-text search for emails using BM25.

BM25-ranked search across all synced email accounts.
Returns complete email entities ordered by relevance.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from daemon.sync.storage import load_all_emails, resolve_account

from ..base import tool
from .fts import SearchIndex, create_email_text_extractor

logger = logging.getLogger("qwen.tools.google.fts")


# --- Date Parsing ---


def _parse_email_date(date_str: str) -> datetime | None:
    """Parse email date (RFC 2822 format)."""
    if not date_str:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


def _parse_filter_date(date_str: str) -> datetime | None:
    """Parse filter date (YYYY-MM-DD format)."""
    formats = ["%Y-%m-%d", "%Y/%m/%d"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


# --- Index Singleton ---

_email_index: SearchIndex[dict[str, Any]] | None = None


def _get_email_index() -> SearchIndex[dict[str, Any]]:
    """Get or create the email search index (lazy singleton)."""
    global _email_index
    if _email_index is None:
        _email_index = SearchIndex(
            loader=lambda: load_all_emails(None),
            text_extractor=create_email_text_extractor(),
        )
    return _email_index


def invalidate_email_index() -> None:
    """Invalidate the email index cache (call when data changes)."""
    global _email_index
    if _email_index is not None:
        _email_index.invalidate()


# --- Result Formatting ---


def _format_email_result(email: dict[str, Any], score: float, rank: int) -> dict[str, Any]:
    """Format email for response with score."""
    # Format attachments
    attachments = []
    for att in email.get("attachments", []):
        attachments.append({
            "filename": att.get("filename", ""),
            "size": att.get("size", 0),
            "mime_type": att.get("mime_type", ""),
        })

    return {
        "rank": rank,
        "score": round(score, 4),
        "id": email.get("id", ""),
        "account": email.get("account", ""),
        "thread_id": email.get("thread_id", ""),
        "from": email.get("from", ""),
        "to": email.get("to", ""),
        "cc": email.get("cc", ""),
        "subject": email.get("subject", ""),
        "date": email.get("date", ""),
        "body": email.get("body", ""),
        "snippet": email.get("snippet", ""),
        "labels": email.get("label_ids", []),
        "has_attachments": email.get("has_attachments", False),
        "attachments": attachments,
    }


# --- Tool Definition ---


@tool(
    name="search_emails_fts",
    description="""Full-text search across synced emails using BM25 ranking.

Returns emails ranked by relevance to the query. Uses BM25 (Best Match 25) algorithm
which considers term frequency, document length, and inverse document frequency
for high-quality keyword matching.

Searches across: subject, body, snippet, from, and to fields.

Returns complete email entities with relevance scores, not just snippets.
Use this to find relevant emails by keywords or phrases.""",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query - keywords or phrases to find in emails",
            },
            "account": {
                "type": "string",
                "description": "Filter to specific account (e.g., 'ep', 'jm'). If not specified, searches all accounts.",
            },
            "after_date": {
                "type": "string",
                "description": "Only emails after this date (YYYY-MM-DD)",
            },
            "before_date": {
                "type": "string",
                "description": "Only emails before this date (YYYY-MM-DD)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return (default: 20, max: 100)",
            },
        },
        "required": ["query"],
    },
)
def search_emails_fts(
    query: str,
    account: str | None = None,
    after_date: str | None = None,
    before_date: str | None = None,
    limit: int = 20,
) -> str:
    """Full-text search emails with BM25 ranking."""
    # Resolve email address to account shortname if needed
    resolved_account = resolve_account(account) if account else None
    logger.info(f"FTS email search: query='{query}', account={account} (resolved={resolved_account}), limit={limit}")

    # Validate inputs
    if not query or not query.strip():
        return json.dumps({
            "status": "error",
            "error": "Query cannot be empty",
        })

    limit = min(max(1, limit), 100)  # Clamp to 1-100

    # Parse date filters
    after_dt = _parse_filter_date(after_date) if after_date else None
    before_dt = _parse_filter_date(before_date) if before_date else None

    # Build filter function
    def filter_email(email: dict[str, Any]) -> bool:
        # Account filter
        if resolved_account and email.get("account", "") != resolved_account:
            return False

        # Date filters
        email_date = _parse_email_date(email.get("date", ""))
        if email_date:
            email_dt_naive = email_date.replace(tzinfo=None)
            if after_dt and email_dt_naive < after_dt:
                return False
            if before_dt and email_dt_naive > before_dt:
                return False

        return True

    # Get index and search
    index = _get_email_index()
    response = index.search(query, limit=limit, filter_fn=filter_email)

    # Format results
    results = [
        _format_email_result(r.document, r.score, r.rank)
        for r in response.results
    ]

    return json.dumps({
        "status": "success",
        "query": query,
        "count": len(results),
        "total_matches": response.total_matches,
        "index_size": response.index_size,
        "results": results,
    })


TOOL = search_emails_fts
