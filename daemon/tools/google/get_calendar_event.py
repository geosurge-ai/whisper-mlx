"""
Get calendar event tool.

Retrieve full details of a downloaded calendar event by ID.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from daemon.sync.storage import list_all_accounts_with_data, load_event, resolve_account

from ..base import tool

logger = logging.getLogger("qwen.tools.google")


@tool(
    name="get_calendar_event",
    description="""Retrieve full details of a downloaded calendar event by its ID.

Returns complete event information including description, attendees, and conference details.
Use search_calendar first to find event IDs.""",
    parameters={
        "type": "object",
        "properties": {
            "event_id": {
                "type": "string",
                "description": "The event ID (from search_calendar results)",
            },
            "account": {
                "type": "string",
                "description": "Account name where the event is stored. If not specified, searches all accounts.",
            },
        },
        "required": ["event_id"],
    },
)
def get_calendar_event(
    event_id: str,
    account: str | None = None,
) -> str:
    """Get full calendar event details by ID."""
    # Resolve email address to account shortname if needed
    resolved_account = resolve_account(account) if account else None
    logger.info(f"Getting calendar event: id={event_id}, account={account} (resolved={resolved_account})")

    # If account specified, load directly
    if resolved_account:
        event = load_event(resolved_account, event_id)
        if event:
            return json.dumps({
                "status": "success",
                "event": _format_event(event),
            })
        return json.dumps({
            "status": "error",
            "error": f"Event {event_id} not found in account '{resolved_account}'",
        })

    # Search across all accounts
    accounts = list_all_accounts_with_data()
    for acc in accounts:
        event = load_event(acc, event_id)
        if event:
            return json.dumps({
                "status": "success",
                "event": _format_event(event),
            })

    return json.dumps({
        "status": "error",
        "error": f"Event {event_id} not found in any account",
    })


def _format_event(event: dict[str, Any]) -> dict[str, Any]:
    """Format event for response."""
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
        "reminders": event.get("reminders", {}),
        "created": event.get("created", ""),
        "updated": event.get("updated", ""),
        "synced_at": event.get("synced_at", ""),
    }


TOOL = get_calendar_event
