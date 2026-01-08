"""
Search calendar tool.

Searches through synced Google Calendar events.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..base import tool
from ...sync.storage import get_calendar_events_dir, list_calendar_events

logger = logging.getLogger("qwen.tools.google")


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse date string to datetime."""
    if not date_str:
        return None
    try:
        # Handle ISO format with timezone
        if "T" in date_str:
            if date_str.endswith("Z"):
                date_str = date_str[:-1] + "+00:00"
            return datetime.fromisoformat(date_str)
        # Handle date-only format (all-day events)
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _matches_query(event: dict[str, Any], query: str) -> bool:
    """Check if event matches text query."""
    query_lower = query.lower()
    
    # Search in summary, description, and location
    searchable = [
        event.get("summary", ""),
        event.get("description", ""),
        event.get("location", ""),
    ]
    
    for field in searchable:
        if query_lower in field.lower():
            return True
    
    return False


def _in_date_range(
    event: dict[str, Any],
    after: datetime | None,
    before: datetime | None,
) -> bool:
    """Check if event is within date range."""
    event_start = _parse_date(event.get("start"))
    if not event_start:
        return True  # Include events without dates
    
    if after and event_start < after:
        return False
    
    if before and event_start > before:
        return False
    
    return True


@tool(
    name="search_calendar",
    description="""Search through synced Google Calendar events.

Use this tool to find calendar events by:
- Text search (title, description, location)
- Date range
- Calendar ID

Returns a list of matching events. Use get_calendar_event for full details.

Common date range shortcuts:
- "today" - events happening today
- "this_week" - events in the current week
- "next_week" - events in the next 7 days""",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text to search for in title, description, and location",
            },
            "date_range": {
                "type": "string",
                "description": "Date range shortcut: 'today', 'this_week', 'next_week', or custom ISO dates",
            },
            "after": {
                "type": "string",
                "description": "Only events after this date (ISO format: 2024-01-15)",
            },
            "before": {
                "type": "string",
                "description": "Only events before this date (ISO format: 2024-01-15)",
            },
            "calendar_id": {
                "type": "string",
                "description": "Filter by calendar ID (partial match)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default: 50)",
            },
        },
        "required": [],
    },
)
def search_calendar(
    query: str = "",
    date_range: str = "",
    after: str = "",
    before: str = "",
    calendar_id: str = "",
    limit: int = 50,
) -> str:
    """Search through synced calendar events."""
    events_dir = get_calendar_events_dir()
    event_files = list_calendar_events()
    
    if not event_files:
        return json.dumps({
            "status": "success",
            "message": "No calendar events synced yet. Sync will run automatically.",
            "results": [],
            "total": 0,
        })
    
    # Handle date range shortcuts
    now = datetime.now(timezone.utc)
    after_dt: datetime | None = None
    before_dt: datetime | None = None
    
    if date_range == "today":
        after_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        before_dt = after_dt + timedelta(days=1)
    elif date_range == "this_week":
        # Start of week (Monday)
        after_dt = now - timedelta(days=now.weekday())
        after_dt = after_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        before_dt = after_dt + timedelta(days=7)
    elif date_range == "next_week":
        after_dt = now
        before_dt = now + timedelta(days=7)
    else:
        if after:
            after_dt = _parse_date(after)
        if before:
            before_dt = _parse_date(before)
    
    results: list[dict[str, Any]] = []
    
    for event_file in event_files:
        try:
            with open(event_file) as f:
                event = json.load(f)
            
            # Apply filters
            if query and not _matches_query(event, query):
                continue
            if not _in_date_range(event, after_dt, before_dt):
                continue
            if calendar_id and calendar_id.lower() not in event.get("calendar_id", "").lower():
                continue
            
            # Build result summary
            results.append({
                "id": event["id"],
                "summary": event.get("summary", "(No title)"),
                "start": event.get("start", ""),
                "end": event.get("end", ""),
                "is_all_day": event.get("is_all_day", False),
                "location": event.get("location", ""),
                "calendar_name": event.get("calendar_name", ""),
                "status": event.get("status", ""),
                "recurring": event.get("recurring", False),
            })
            
            if len(results) >= limit:
                break
                
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read event {event_file}: {e}")
            continue
    
    # Sort by start date (soonest first)
    results.sort(key=lambda x: x.get("start", ""))
    
    return json.dumps({
        "status": "success",
        "results": results,
        "total": len(results),
        "limit": limit,
    })


TOOL = search_calendar
