"""
Full-text search for calendar events using BM25.

BM25-ranked search across all synced calendar accounts.
Returns complete event entities ordered by relevance.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from daemon.sync.storage import load_all_events, resolve_account

from ..base import tool
from .fts import SearchIndex, create_calendar_text_extractor

logger = logging.getLogger("qwen.tools.google.fts")


# --- Date Parsing ---


def _parse_event_datetime(dt_str: str) -> datetime | None:
    """Parse event start/end datetime."""
    if not dt_str:
        return None

    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(dt_str.replace("Z", "+00:00"), fmt)
        except ValueError:
            continue

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

_calendar_index: SearchIndex[dict[str, Any]] | None = None


def _get_calendar_index() -> SearchIndex[dict[str, Any]]:
    """Get or create the calendar search index (lazy singleton)."""
    global _calendar_index
    if _calendar_index is None:
        _calendar_index = SearchIndex(
            loader=lambda: load_all_events(None),
            text_extractor=create_calendar_text_extractor(),
        )
    return _calendar_index


def invalidate_calendar_index() -> None:
    """Invalidate the calendar index cache (call when data changes)."""
    global _calendar_index
    if _calendar_index is not None:
        _calendar_index.invalidate()


# --- Result Formatting ---


def _format_event_result(event: dict[str, Any], score: float, rank: int) -> dict[str, Any]:
    """Format calendar event for response with score."""
    # Format attendees
    attendees = []
    for att in event.get("attendees", []):
        attendees.append({
            "email": att.get("email", ""),
            "name": att.get("display_name", ""),
            "response": att.get("response_status", ""),
            "organizer": att.get("organizer", False),
        })

    # Extract conference info
    conference = {}
    conf_data = event.get("conference_data", {})
    if conf_data:
        entry_points = conf_data.get("entryPoints", [])
        for ep in entry_points:
            if ep.get("entryPointType") == "video":
                conference["video_url"] = ep.get("uri", "")
            elif ep.get("entryPointType") == "phone":
                conference["phone"] = ep.get("uri", "")

    return {
        "rank": rank,
        "score": round(score, 4),
        "id": event.get("id", ""),
        "account": event.get("account", ""),
        "calendar_id": event.get("calendar_id", ""),
        "calendar_name": event.get("calendar_name", ""),
        "summary": event.get("summary", ""),
        "description": event.get("description", ""),
        "location": event.get("location", ""),
        "start": event.get("start", ""),
        "end": event.get("end", ""),
        "all_day": event.get("all_day", False),
        "timezone": event.get("timezone", ""),
        "status": event.get("status", ""),
        "html_link": event.get("html_link", ""),
        "organizer": event.get("organizer", {}),
        "creator": event.get("creator", {}),
        "attendees": attendees,
        "conference": conference,
        "recurring_event_id": event.get("recurring_event_id", ""),
    }


# --- Tool Definition ---


@tool(
    name="search_calendar_fts",
    description="""Full-text search across synced calendar events using BM25 ranking.

Returns events ranked by relevance to the query. Uses BM25 (Best Match 25) algorithm
which considers term frequency, document length, and inverse document frequency
for high-quality keyword matching.

Searches across: summary (title), description, location, and attendee names/emails.

Returns complete event entities with relevance scores, not just summaries.
Use this to find relevant calendar events by keywords or phrases.""",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query - keywords or phrases to find in events",
            },
            "account": {
                "type": "string",
                "description": "Filter to specific account (e.g., 'ep', 'jm'). If not specified, searches all accounts.",
            },
            "after_date": {
                "type": "string",
                "description": "Only events starting after this date (YYYY-MM-DD)",
            },
            "before_date": {
                "type": "string",
                "description": "Only events starting before this date (YYYY-MM-DD)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return (default: 20, max: 100)",
            },
        },
        "required": ["query"],
    },
)
def search_calendar_fts(
    query: str,
    account: str | None = None,
    after_date: str | None = None,
    before_date: str | None = None,
    limit: int = 20,
) -> str:
    """Full-text search calendar events with BM25 ranking."""
    # Resolve email address to account shortname if needed
    resolved_account = resolve_account(account) if account else None
    logger.info(f"FTS calendar search: query='{query}', account={account} (resolved={resolved_account}), limit={limit}")

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
    def filter_event(event: dict[str, Any]) -> bool:
        # Account filter
        if resolved_account and event.get("account", "") != resolved_account:
            return False

        # Date filters (on event start time)
        event_start = _parse_event_datetime(event.get("start", ""))
        if event_start:
            event_dt_naive = event_start.replace(tzinfo=None)
            if after_dt and event_dt_naive < after_dt:
                return False
            if before_dt and event_dt_naive > before_dt:
                return False

        return True

    # Get index and search
    index = _get_calendar_index()
    response = index.search(query, limit=limit, filter_fn=filter_event)

    # Format results
    results = [
        _format_event_result(r.document, r.score, r.rank)
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


TOOL = search_calendar_fts
