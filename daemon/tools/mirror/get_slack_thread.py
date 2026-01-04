"""
Get Slack thread tool.

Get all messages in a specific Slack thread.
"""

import json

from ..base import tool
from .data_store import get_data_store


@tool(
    name="get_slack_thread",
    description="Get the full conversation in a Slack thread. Use this after finding a relevant thread via search_slack_messages.",
    parameters={
        "type": "object",
        "properties": {
            "channel_id": {
                "type": "string",
                "description": "The Slack channel ID (e.g., C08D0GTKWLD)",
            },
            "thread_ts": {
                "type": "string",
                "description": "The thread timestamp (e.g., 1700000000.123456)",
            },
        },
        "required": ["channel_id", "thread_ts"],
    },
)
def get_slack_thread(channel_id: str, thread_ts: str) -> str:
    """Get all messages in a Slack thread."""
    store = get_data_store()
    messages = store.get_slack_thread(channel_id, thread_ts)

    if not messages:
        return json.dumps({
            "error": f"Thread not found: {channel_id}/{thread_ts}",
            "hint": "The thread_ts should use dots (e.g., 1700000000.123456)",
        })

    messages.sort(key=lambda m: m.ts)

    formatted = []
    for msg in messages:
        text = msg.text or ""
        if len(text) > 1000:
            text = text[:1000] + "...(truncated)"

        formatted.append({
            "ts": msg.ts,
            "user": store.resolve_slack_user(msg.user),
            "text": text,
        })

    return json.dumps({
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "message_count": len(formatted),
        "messages": formatted,
    })


TOOL = get_slack_thread
