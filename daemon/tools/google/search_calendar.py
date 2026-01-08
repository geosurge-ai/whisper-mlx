"""
Search calendar events tool.

Search locally synced calendar events by various criteria.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from daemon.sync.storage import load_all_events

from ..base import tool

logger = logging.getLogger("qwen.tools.google")


def _parse_date(date_str: str) -> datetime | None:
    """Try to parse a date string in various formats."""
    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _parse_event_datetime(dt_str: str) -> datetime | None:
    """Parse event start/end datetime."""
    if not dt_str:
        return None

    # Try ISO format with timezone
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


def _event_matches_criteria(
    event: dict[str, Any],
    query: str | None,
    after_date: str | None,
    before_date: str | None,
    calendar_name: str | None,
    attendee: str | None,
    account: str | None,
) -> bool:
    """Check if an event matches the search criteria."""
    # Account filter
    if account and event.get("account", "") != account:
        return False

    # Calendar name filter
    if calendar_name:
        event_cal = event.get("calendar_name", "").lower()
        if calendar_name.lower() not in event_cal:
            return False

    # Full-text query
    if query:
        query_lower = query.lower()
        searchable = " ".join([
            event.get("summary", ""),
            event.get("description", ""),
            event.get("location", ""),
        ]).lower()
        if not re.search(re.escape(query_lower), searchable):
            return False

    # Date filters (on event start time)
    event_start = _parse_event_datetime(event.get("start", ""))
    if event_start:
        if after_date:
            after = _parse_date(after_date)
            if after and event_start.replace(tzinfo=None) < after:
                return False

        if before_date:
            before = _parse_date(before_date)
            if before and event_start.replace(tzinfo=None) > before:
                return False

    # Attendee filter
    if attendee:
        attendee_lower = attendee.lower()
        found = False
        for att in event.get("attendees", []):
            email = att.get("email", "").lower()
            name = att.get("display_name", "").lower()
            if attendee_lower in email or attendee_lower in name:
                found = True
                break
        if not found:
            return False

    return True


@tool(
    name="search_calendar",
    description="""Search downloaded calendar events by various criteria.

Searches across all synced Google Calendar accounts unless a specific account is specified.
Returns matching events with details.

Use this to find events by title, description, date range, or attendees.""",
    parameters={
        "type": "object",
        "properties": {
            "account": {
                "type": "string",
                "description": "Account name to search (e.g., 'ep', 'jm'). If not specified, searches all accounts.",
            },
            "query": {
                "type": "string",
                "description": "Search in event title, description, and location",
            },
            "after_date": {
                "type": "string",
                "description": "Only events starting after this date (YYYY-MM-DD)",
            },
            "before_date": {
                "type": "string",
                "description": "Only events starting before this date (YYYY-MM-DD)",
            },
            "calendar_name": {
                "type": "string",
                "description": "Filter by calendar name (partial match)",
            },
            "attendee": {
                "type": "string",
                "description": "Filter by attendee email or name (partial match)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default: 20)",
            },
        },
        "required": [],
    },
)
def search_calendar(
    account: str | None = None,
    query: str | None = None,
    after_date: str | None = None,
    before_date: str | None = None,
    calendar_name: str | None = None,
    attendee: str | None = None,
    limit: int = 20,
) -> str:
    """Search downloaded calendar events."""
    logger.info(f"Searching calendar: account={account}, query={query}, after={after_date}")

    # Load all events (optionally filtered by account)
    all_events = load_all_events(account)

    if not all_events:
        return json.dumps({
            "status": "success",
            "count": 0,
            "message": "No events found. Events may not be synced yet.",
            "results": [],
        })

    # Filter events
    matching: list[dict[str, Any]] = []
    for event in all_events:
        if _event_matches_criteria(
            event,
            query,
            after_date,
            before_date,
            calendar_name,
            attendee,
            account,
        ):
            matching.append({
                "id": event.get("id", ""),
                "account": event.get("account", ""),
                "summary": event.get("summary", ""),
                "start": event.get("start", ""),
                "end": event.get("end", ""),
                "all_day": event.get("all_day", False),
                "location": event.get("location", ""),
                "calendar_name": event.get("calendar_name", ""),
                "status": event.get("status", ""),
                "attendee_count": len(event.get("attendees", [])),
            })

    # Sort by start time
    matching.sort(key=lambda x: x.get("start", ""))

    # Apply limit
    results = matching[:limit]

    return json.dumps({
        "status": "success",
        "count": len(results),
        "total_matches": len(matching),
        "results": results,
    })


TOOL = search_calendar
