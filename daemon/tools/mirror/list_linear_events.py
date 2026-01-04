"""
List Linear events tool.

List recent Linear activity: state changes, assignments, comments, etc.
"""

import json
from datetime import datetime, timedelta, timezone

from ..base import tool
from .data_store import get_data_store


@tool(
    name="list_linear_events",
    description="List recent Linear activity: state changes, assignments, comments, etc. Good for understanding what happened recently. Use get_current_datetime first to understand 'today'.",
    parameters={
        "type": "object",
        "properties": {
            "since_days": {
                "type": "integer",
                "description": "How many days back to look (default 7, no limit)",
            },
            "event_type": {
                "type": "string",
                "description": "Filter by event type (e.g., 'state', 'assignee', 'comment')",
            },
            "actor": {
                "type": "string",
                "description": "Filter by who made the change (name)",
            },
            "limit": {
                "type": "integer",
                "description": "Max results per page (default 20)",
            },
            "page": {
                "type": "integer",
                "description": "Page number for pagination (0-indexed)",
            },
        },
        "required": [],
    },
)
def list_linear_events(
    since_days: int = 7,
    event_type: str | None = None,
    actor: str | None = None,
    limit: int = 20,
    page: int = 0,
) -> str:
    """List recent Linear events."""
    store = get_data_store()
    events = store.get_linear_events()

    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    cutoff_str = cutoff.isoformat()

    filtered = []
    for event in events:
        if event.created_at < cutoff_str:
            continue

        if event_type and event_type.lower() not in event.event_kind.lower():
            continue

        if actor and event.actor_name:
            if actor.lower() not in event.actor_name.lower():
                continue
        elif actor and not event.actor_name:
            continue

        filtered.append(event)

    total = len(filtered)
    start = page * limit
    end = start + limit
    page_items = filtered[start:end]

    results = []
    for event in page_items:
        result = {
            "issue": event.issue_identifier,
            "event": event.event_kind,
            "actor": event.actor_name,
            "timestamp": event.created_at[:16].replace("T", " "),
        }
        if event.from_state or event.to_state:
            result["transition"] = f"{event.from_state or '?'} → {event.to_state or '?'}"
        results.append(result)

    return json.dumps({
        "total": total,
        "page": page,
        "page_size": limit,
        "has_more": end < total,
        "since_days": since_days,
        "events": results,
    })


TOOL = list_linear_events
