"""
Search Slack messages tool.

Search Slack messages across all channels and threads.
"""

import json

from ..base import tool
from .data_store import get_data_store


@tool(
    name="search_slack_messages",
    description="Search Slack messages across all channels and threads. Returns matching messages with context to drill down into specific threads.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term to match in message text",
            },
            "channel": {
                "type": "string",
                "description": "Optional channel ID to limit search (e.g., C08D0GTKWLD)",
            },
            "limit": {
                "type": "integer",
                "description": "Max results per page (default 10)",
            },
            "page": {
                "type": "integer",
                "description": "Page number for pagination (0-indexed)",
            },
        },
        "required": ["query"],
    },
)
def search_slack_messages(
    query: str,
    channel: str | None = None,
    limit: int = 10,
    page: int = 0,
) -> str:
    """Search Slack messages."""
    store = get_data_store()
    query_lower = query.lower()

    matches = []

    # Search conversations
    for channel_id, msg in store.stream_slack_conversations():
        if channel and channel.lower() not in channel_id.lower():
            continue

        if msg.text and query_lower in msg.text.lower():
            matches.append({
                "source": "conversation",
                "channel_id": channel_id,
                "thread_ts": msg.thread_ts,
                "ts": msg.ts,
                "user": store.resolve_slack_user(msg.user),
                "text": msg.text[:200] if len(msg.text) > 200 else msg.text,
                "reply_count": msg.reply_count,
            })

    # Search threads
    thread_count = 0
    max_threads = 1000
    for channel_id, thread_ts, msg in store.stream_slack_threads():
        if thread_count > max_threads:
            break
        thread_count += 1

        if channel and channel.lower() not in channel_id.lower():
            continue

        if msg.text and query_lower in msg.text.lower():
            matches.append({
                "source": "thread",
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "ts": msg.ts,
                "user": store.resolve_slack_user(msg.user),
                "text": msg.text[:200] if len(msg.text) > 200 else msg.text,
            })

    matches.sort(key=lambda m: m["ts"], reverse=True)

    total = len(matches)
    start = page * limit
    end = start + limit
    page_items = matches[start:end]

    return json.dumps({
        "total": total,
        "page": page,
        "page_size": limit,
        "has_more": end < total,
        "messages": page_items,
    })


TOOL = search_slack_messages
