"""
Get calendar event tool.

Retrieves full details of a specific calendar event by ID.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..base import tool
from ...sync.storage import load_calendar_event

logger = logging.getLogger("qwen.tools.google")


@tool(
    name="get_calendar_event",
    description="""Get full details of a specific calendar event by ID.

Use this after search_calendar to get complete event details including:
- Full description
- All attendees
- Organizer information
- Recurrence information
- Links

The event_id comes from search_calendar results.""",
    parameters={
        "type": "object",
        "properties": {
            "event_id": {
                "type": "string",
                "description": "The event ID from search_calendar results",
            },
        },
        "required": ["event_id"],
    },
)
def get_calendar_event(event_id: str) -> str:
    """Get full details of a specific calendar event."""
    event = load_calendar_event(event_id)
    
    if event is None:
        return json.dumps({
            "status": "error",
            "error": f"Event not found: {event_id}",
        })
    
    return json.dumps({
        "status": "success",
        "event": event,
    })


TOOL = get_calendar_event
