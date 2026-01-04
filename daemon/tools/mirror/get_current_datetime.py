"""
Get current datetime tool.

Use this to orient in time before answering questions about time periods.
"""

import json
from datetime import datetime, timedelta, timezone

from ..base import tool


@tool(
    name="get_current_datetime",
    description="Get the current date and time. ALWAYS call this first when answering questions about time periods like 'last week', 'this month', 'past 2 months', 'recently', etc. Returns UTC and local time with helpful date range hints.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def get_current_datetime() -> str:
    """Get the current date and time with helpful hints."""
    now = datetime.now(timezone.utc)
    local_now = datetime.now()
    
    return json.dumps({
        "utc": {
            "iso": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "day_of_week": now.strftime("%A"),
            "timestamp": now.timestamp(),
        },
        "local": {
            "iso": local_now.isoformat(),
            "date": local_now.strftime("%Y-%m-%d"),
            "time": local_now.strftime("%H:%M:%S"),
            "day_of_week": local_now.strftime("%A"),
        },
        "hints": {
            "last_7_days": f"{(now - timedelta(days=7)).strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}",
            "last_30_days": f"{(now - timedelta(days=30)).strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}",
            "last_90_days": f"{(now - timedelta(days=90)).strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}",
        },
    })


TOOL = get_current_datetime
