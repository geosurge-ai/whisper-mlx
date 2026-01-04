"""
List recent Slack activity tool.

List active Slack threads sorted by recent activity.
"""

import json
from datetime import datetime, timedelta, timezone

from ..base import tool
from .data_store import get_data_store


@tool(
    name="list_recent_slack_activity",
    description="List active Slack threads/conversations. Aggregates messages by thread and returns threads sorted by recent activity. Shows thread topic, reply count, participants, and last activity. Use get_current_datetime first for time-based queries.",
    parameters={
        "type": "object",
        "properties": {
            "since_days": {
                "type": "integer",
                "description": "How many days back to look (default 7, no limit)",
            },
            "channel": {
                "type": "string",
                "description": "Optional channel ID to limit to a specific channel",
            },
            "limit": {
                "type": "integer",
                "description": "Max threads per page (default 15)",
            },
            "page": {
                "type": "integer",
                "description": "Page number for pagination (0-indexed)",
            },
        },
        "required": [],
    },
)
def list_recent_slack_activity(
    since_days: int = 7,
    channel: str | None = None,
    limit: int = 15,
    page: int = 0,
) -> str:
    """List active Slack threads."""
    store = get_data_store()

    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    cutoff_ts = str(cutoff.timestamp())

    threads: dict[tuple[str, str], dict] = {}

    # Collect from conversations
    for channel_id, msg in store.stream_slack_conversations():
        if channel and channel.lower() not in channel_id.lower():
            continue

        if not msg.text or not msg.text.strip():
            continue

        thread_key = (channel_id, msg.thread_ts or msg.ts)
        
        if thread_key not in threads:
            threads[thread_key] = {
                "channel_id": channel_id,
                "thread_ts": msg.thread_ts or msg.ts,
                "first_message": msg.text[:200] if len(msg.text) > 200 else msg.text,
                "first_author": store.resolve_slack_user(msg.user),
                "reply_count": msg.reply_count or 0,
                "participants": set(),
                "last_activity_ts": msg.ts,
                "recent_message_count": 0,
            }
        
        thread = threads[thread_key]
        if msg.user:
            thread["participants"].add(store.resolve_slack_user(msg.user))
        
        if msg.ts >= cutoff_ts:
            thread["recent_message_count"] += 1
            if msg.ts > thread["last_activity_ts"]:
                thread["last_activity_ts"] = msg.ts

    # Collect from threads
    for channel_id, thread_ts, msg in store.stream_slack_threads():
        if channel and channel.lower() not in channel_id.lower():
            continue

        if not msg.text or not msg.text.strip():
            continue

        thread_key = (channel_id, thread_ts)
        
        if thread_key not in threads:
            threads[thread_key] = {
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "first_message": msg.text[:200] if len(msg.text) > 200 else msg.text,
                "first_author": store.resolve_slack_user(msg.user),
                "reply_count": 0,
                "participants": set(),
                "last_activity_ts": msg.ts,
                "recent_message_count": 0,
            }
        
        thread = threads[thread_key]
        if msg.user:
            thread["participants"].add(store.resolve_slack_user(msg.user))
        thread["reply_count"] += 1
        
        if msg.ts >= cutoff_ts:
            thread["recent_message_count"] += 1
            if msg.ts > thread["last_activity_ts"]:
                thread["last_activity_ts"] = msg.ts

    # Filter to active threads
    active_threads = [t for t in threads.values() if t["recent_message_count"] > 0]
    active_threads.sort(key=lambda t: t["last_activity_ts"], reverse=True)

    total = len(active_threads)
    start = page * limit
    end = start + limit
    page_items = active_threads[start:end]

    formatted_threads = []
    for thread in page_items:
        try:
            ts_float = float(thread["last_activity_ts"])
            dt = datetime.fromtimestamp(ts_float, tz=timezone.utc)
            last_activity = dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            last_activity = "unknown"

        formatted_threads.append({
            "channel_id": thread["channel_id"],
            "thread_ts": thread["thread_ts"],
            "topic_preview": thread["first_message"],
            "started_by": thread["first_author"],
            "reply_count": thread["reply_count"],
            "recent_messages": thread["recent_message_count"],
            "participants": list(thread["participants"])[:5],
            "participant_count": len(thread["participants"]),
            "last_activity": last_activity,
        })

    return json.dumps({
        "total_active_threads": total,
        "page": page,
        "page_size": limit,
        "has_more": end < total,
        "since_days": since_days,
        "threads": formatted_threads,
    })


TOOL = list_recent_slack_activity
