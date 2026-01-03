#!/usr/bin/env python3
"""
Mirror Knowledge Agent: Conversational interface to Linear and Slack mirrors.

Uses Qwen 32B with tool-calling to answer questions about your workspace's
Linear issues and Slack conversations. Implements smart pagination to handle
large datasets without overwhelming the LLM context.

Data sources:
- Linear mirror: issues, comments, events, users (JSONL format)
- Slack mirror: conversations, threads, profiles (JSONL format)
"""

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from llm import Tool, ToolCallingAgent


# --- Configuration ---

DEFAULT_LINEAR_MIRROR = Path.home() / "Github" / "vibe-os" / "linear_mirror"
DEFAULT_SLACK_MIRROR = Path.home() / "Github" / "vibe-os" / "slack_mirror"

LINEAR_MIRROR_DIR = Path(os.environ.get("LINEAR_MIRROR_DIR", DEFAULT_LINEAR_MIRROR))
SLACK_MIRROR_DIR = Path(os.environ.get("VIBEOS_SLACK_MIRROR_DIR", DEFAULT_SLACK_MIRROR))


# --- Data Types ---

@dataclass
class LinearIssue:
    """Linear issue snapshot."""
    id: str
    identifier: str
    title: str
    description: str | None
    url: str | None
    team_name: str | None
    state_name: str | None
    state_type: str | None
    assignee_name: str | None
    labels: list[str]
    priority: int | None
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, data: dict) -> "LinearIssue":
        return cls(
            id=data.get("id", ""),
            identifier=data.get("identifier", ""),
            title=data.get("title", ""),
            description=data.get("description"),
            url=data.get("url"),
            team_name=data.get("team_name"),
            state_name=data.get("state_name"),
            state_type=data.get("state_type"),
            assignee_name=data.get("assignee_name"),
            labels=data.get("labels", []),
            priority=data.get("priority"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass
class LinearEvent:
    """Linear issue event."""
    id: str
    issue_id: str
    issue_identifier: str
    event_kind: str
    created_at: str
    actor_name: str | None
    from_state: str | None
    to_state: str | None

    @classmethod
    def from_dict(cls, data: dict) -> "LinearEvent":
        return cls(
            id=data.get("id", ""),
            issue_id=data.get("issue_id", ""),
            issue_identifier=data.get("issue_identifier", ""),
            event_kind=data.get("event_kind", ""),
            created_at=data.get("created_at", ""),
            actor_name=data.get("actor_name"),
            from_state=data.get("from_state"),
            to_state=data.get("to_state"),
        )


@dataclass
class LinearComment:
    """Linear comment record."""
    id: str
    issue_id: str
    issue_identifier: str | None
    body: str
    created_at: str
    user_name: str | None

    @classmethod
    def from_dict(cls, data: dict) -> "LinearComment":
        return cls(
            id=data.get("id", ""),
            issue_id=data.get("issue_id", ""),
            issue_identifier=data.get("issue_identifier"),
            body=data.get("body", ""),
            created_at=data.get("created_at", ""),
            user_name=data.get("user_name") or data.get("user_display_name"),
        )


@dataclass
class SlackMessage:
    """Slack message."""
    ts: str
    user: str | None
    text: str | None
    thread_ts: str | None
    reply_count: int | None

    @classmethod
    def from_dict(cls, data: dict) -> "SlackMessage":
        return cls(
            ts=data.get("ts", ""),
            user=data.get("user"),
            text=data.get("text"),
            thread_ts=data.get("thread_ts"),
            reply_count=data.get("reply_count"),
        )


# --- Data Access Layer ---

class MirrorDataStore:
    """
    Lazy-loading data store for Linear and Slack mirrors.
    
    Caches loaded data in memory for the session duration.
    Uses streaming for large files to avoid memory issues.
    """
    
    def __init__(
        self,
        linear_dir: Path = LINEAR_MIRROR_DIR,
        slack_dir: Path = SLACK_MIRROR_DIR,
    ):
        self.linear_dir = linear_dir
        self.slack_dir = slack_dir
        
        # Caches
        self._linear_issues: list[LinearIssue] | None = None
        self._linear_comments: dict[str, list[LinearComment]] | None = None
        self._linear_events: list[LinearEvent] | None = None
        self._linear_users: dict[str, dict] | None = None
        self._slack_profiles: dict[str, dict] | None = None
        self._slack_channel_names: dict[str, str] | None = None
    
    # --- JSONL Utilities ---
    
    @staticmethod
    def _read_jsonl(path: Path) -> Iterator[dict]:
        """Stream JSONL file line by line."""
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
    
    @staticmethod
    def _read_jsonl_list(path: Path) -> list[dict]:
        """Read entire JSONL file into list."""
        return list(MirrorDataStore._read_jsonl(path))
    
    # --- Linear Data Access ---
    
    def get_linear_issues(self) -> list[LinearIssue]:
        """Load all Linear issues (cached)."""
        if self._linear_issues is None:
            path = self.linear_dir / "issues.jsonl"
            self._linear_issues = [
                LinearIssue.from_dict(d) for d in self._read_jsonl(path)
            ]
        return self._linear_issues
    
    def get_linear_comments(self) -> dict[str, list[LinearComment]]:
        """Load Linear comments grouped by issue_id (cached)."""
        if self._linear_comments is None:
            path = self.linear_dir / "comments.jsonl"
            self._linear_comments = {}
            for d in self._read_jsonl(path):
                comment = LinearComment.from_dict(d)
                if comment.issue_id not in self._linear_comments:
                    self._linear_comments[comment.issue_id] = []
                self._linear_comments[comment.issue_id].append(comment)
        return self._linear_comments
    
    def get_linear_events(self) -> list[LinearEvent]:
        """Load all Linear events from rotated log files (cached)."""
        if self._linear_events is None:
            self._linear_events = []
            # Find all event log files
            for path in sorted(self.linear_dir.glob("events.*.jsonl")):
                for d in self._read_jsonl(path):
                    self._linear_events.append(LinearEvent.from_dict(d))
            # Sort by created_at descending (most recent first)
            self._linear_events.sort(key=lambda e: e.created_at, reverse=True)
        return self._linear_events
    
    def get_linear_users(self) -> dict[str, dict]:
        """Load Linear user profiles (cached)."""
        if self._linear_users is None:
            self._linear_users = {}
            users_dir = self.linear_dir / "users"
            if users_dir.exists():
                for path in users_dir.glob("*.jsonl"):
                    # Read the last snapshot (most recent)
                    snapshots = self._read_jsonl_list(path)
                    if snapshots:
                        last = snapshots[-1]
                        user = last.get("user", {})
                        user_id = user.get("id", path.stem)
                        self._linear_users[user_id] = user
        return self._linear_users
    
    # --- Slack Data Access ---
    
    def get_slack_profiles(self) -> dict[str, dict]:
        """Load Slack user profiles (cached)."""
        if self._slack_profiles is None:
            self._slack_profiles = {}
            profiles_dir = self.slack_dir / "profiles"
            if profiles_dir.exists():
                for path in profiles_dir.glob("*.jsonl"):
                    snapshots = self._read_jsonl_list(path)
                    if snapshots:
                        last = snapshots[-1]
                        user = last.get("user", {})
                        user_id = user.get("id", path.stem)
                        self._slack_profiles[user_id] = user
        return self._slack_profiles
    
    def get_slack_channel_names(self) -> dict[str, str]:
        """Build channel ID to name mapping from conversation files."""
        if self._slack_channel_names is None:
            self._slack_channel_names = {}
            convos_dir = self.slack_dir / "conversations"
            if convos_dir.exists():
                for path in convos_dir.glob("*.jsonl"):
                    channel_id = path.stem
                    # Try to find channel name from first message or use ID
                    self._slack_channel_names[channel_id] = channel_id
        return self._slack_channel_names
    
    def stream_slack_conversations(self) -> Iterator[tuple[str, SlackMessage]]:
        """Stream all Slack conversation messages with channel ID."""
        convos_dir = self.slack_dir / "conversations"
        if not convos_dir.exists():
            return
        for path in convos_dir.glob("*.jsonl"):
            channel_id = path.stem
            for d in self._read_jsonl(path):
                yield channel_id, SlackMessage.from_dict(d)
    
    def stream_slack_threads(self) -> Iterator[tuple[str, str, SlackMessage]]:
        """Stream all Slack thread messages with channel ID and thread_ts."""
        threads_dir = self.slack_dir / "threads"
        if not threads_dir.exists():
            return
        for path in threads_dir.glob("*.jsonl"):
            # Filename format: {channel_id}_{thread_ts}.jsonl
            name = path.stem
            parts = name.split("_", 1)
            if len(parts) == 2:
                channel_id, thread_ts = parts
                thread_ts = thread_ts.replace("_", ".")
                for d in self._read_jsonl(path):
                    yield channel_id, thread_ts, SlackMessage.from_dict(d)
    
    def get_slack_thread(self, channel_id: str, thread_ts: str) -> list[SlackMessage]:
        """Load a specific Slack thread."""
        sanitized_ts = thread_ts.replace(".", "_")
        path = self.slack_dir / "threads" / f"{channel_id}_{sanitized_ts}.jsonl"
        if not path.exists():
            return []
        return [SlackMessage.from_dict(d) for d in self._read_jsonl(path)]
    
    # --- User Resolution ---
    
    def resolve_slack_user(self, user_id: str) -> str:
        """Resolve Slack user ID to display name."""
        if not user_id:
            return "unknown"
        profiles = self.get_slack_profiles()
        if user_id in profiles:
            user = profiles[user_id]
            # Try different name fields
            name = (
                user.get("profile", {}).get("display_name")
                or user.get("profile", {}).get("real_name")
                or user.get("real_name")
                or user.get("name")
                or user_id
            )
            return name
        return user_id
    
    def resolve_linear_user(self, user_id: str) -> str:
        """Resolve Linear user ID to display name."""
        if not user_id:
            return "unknown"
        users = self.get_linear_users()
        if user_id in users:
            user = users[user_id]
            return user.get("displayName") or user.get("name") or user_id
        return user_id


# --- Global Data Store Instance ---

_data_store: MirrorDataStore | None = None


def get_data_store() -> MirrorDataStore:
    """Get or create the global data store instance."""
    global _data_store
    if _data_store is None:
        _data_store = MirrorDataStore()
    return _data_store


# --- Tool Implementations ---

def search_linear_issues(
    query: str = "",
    state: str | None = None,
    assignee: str | None = None,
    label: str | None = None,
    limit: int = 10,
    page: int = 0,
) -> str:
    """
    Search Linear issues with optional filters.
    
    Returns a paginated list of matching issues with summary info.
    """
    store = get_data_store()
    issues = store.get_linear_issues()
    
    # Apply filters
    filtered = []
    query_lower = query.lower() if query else ""
    
    for issue in issues:
        # Text search on title and description
        if query_lower:
            title_match = query_lower in issue.title.lower()
            desc_match = issue.description and query_lower in issue.description.lower()
            if not (title_match or desc_match):
                continue
        
        # State filter
        if state and issue.state_name:
            if state.lower() not in issue.state_name.lower():
                continue
        
        # Assignee filter
        if assignee and issue.assignee_name:
            if assignee.lower() not in issue.assignee_name.lower():
                continue
        elif assignee and not issue.assignee_name:
            continue
        
        # Label filter
        if label:
            label_match = any(label.lower() in l.lower() for l in issue.labels)
            if not label_match:
                continue
        
        filtered.append(issue)
    
    # Sort by updated_at descending
    filtered.sort(key=lambda i: i.updated_at, reverse=True)
    
    # Paginate
    total = len(filtered)
    start = page * limit
    end = start + limit
    page_items = filtered[start:end]
    
    # Format results
    results = []
    for issue in page_items:
        results.append({
            "identifier": issue.identifier,
            "title": issue.title,
            "state": issue.state_name,
            "assignee": issue.assignee_name,
            "team": issue.team_name,
            "labels": issue.labels[:3],  # Limit labels shown
            "updated_at": issue.updated_at[:10],  # Just date
        })
    
    return json.dumps({
        "total": total,
        "page": page,
        "page_size": limit,
        "has_more": end < total,
        "issues": results,
    })


def get_linear_issue(identifier: str) -> str:
    """
    Get full details for a Linear issue by identifier (e.g., FE-42).
    
    Returns the issue with description and recent comments.
    """
    store = get_data_store()
    issues = store.get_linear_issues()
    
    # Find issue by identifier
    issue = next((i for i in issues if i.identifier == identifier), None)
    if not issue:
        return json.dumps({"error": f"Issue {identifier} not found"})
    
    # Get comments for this issue
    comments_by_issue = store.get_linear_comments()
    issue_comments = comments_by_issue.get(issue.id, [])
    
    # Sort comments by date and take recent ones
    issue_comments.sort(key=lambda c: c.created_at, reverse=True)
    recent_comments = issue_comments[:10]
    
    # Format description (truncate if very long)
    description = issue.description or ""
    if len(description) > 2000:
        description = description[:2000] + "...(truncated)"
    
    return json.dumps({
        "identifier": issue.identifier,
        "title": issue.title,
        "url": issue.url,
        "state": issue.state_name,
        "state_type": issue.state_type,
        "assignee": issue.assignee_name,
        "team": issue.team_name,
        "labels": issue.labels,
        "priority": issue.priority,
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
        "description": description,
        "comments": [
            {
                "author": c.user_name,
                "body": c.body[:500] if len(c.body) > 500 else c.body,
                "created_at": c.created_at[:10],
            }
            for c in recent_comments
        ],
    })


def list_linear_events(
    since_days: int = 7,
    event_type: str | None = None,
    actor: str | None = None,
    limit: int = 20,
    page: int = 0,
) -> str:
    """
    List recent Linear events (state changes, assignments, etc.).
    
    Returns paginated list of events within the time window.
    """
    store = get_data_store()
    events = store.get_linear_events()
    
    # Calculate cutoff date
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    cutoff_str = cutoff.isoformat()
    
    # Filter events
    filtered = []
    for event in events:
        # Time filter
        if event.created_at < cutoff_str:
            continue
        
        # Event type filter
        if event_type and event_type.lower() not in event.event_kind.lower():
            continue
        
        # Actor filter
        if actor and event.actor_name:
            if actor.lower() not in event.actor_name.lower():
                continue
        elif actor and not event.actor_name:
            continue
        
        filtered.append(event)
    
    # Already sorted by created_at descending
    total = len(filtered)
    start = page * limit
    end = start + limit
    page_items = filtered[start:end]
    
    # Format results
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


def search_slack_messages(
    query: str,
    channel: str | None = None,
    limit: int = 10,
    page: int = 0,
) -> str:
    """
    Search Slack messages across conversations and threads.
    
    Returns matching messages with context for drilling down into threads.
    """
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
    
    # Search threads (limit to avoid memory issues)
    thread_count = 0
    max_threads = 1000  # Safety limit
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
    
    # Sort by timestamp descending
    matches.sort(key=lambda m: m["ts"], reverse=True)
    
    # Paginate
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


def get_slack_thread(channel_id: str, thread_ts: str) -> str:
    """
    Get all messages in a Slack thread.
    
    Returns the full thread with resolved user names.
    """
    store = get_data_store()
    messages = store.get_slack_thread(channel_id, thread_ts)
    
    if not messages:
        return json.dumps({
            "error": f"Thread not found: {channel_id}/{thread_ts}",
            "hint": "The thread_ts should use dots (e.g., 1700000000.123456)",
        })
    
    # Sort by timestamp
    messages.sort(key=lambda m: m.ts)
    
    # Format messages
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


def lookup_user(user_id_or_name: str, source: str = "both") -> str:
    """
    Look up a user by ID or name in Linear and/or Slack profiles.
    
    Args:
        user_id_or_name: The user ID or name to search for
        source: Where to search - "linear", "slack", or "both"
    """
    store = get_data_store()
    results = []
    search = user_id_or_name.lower()
    
    # Search Linear users
    if source in ("both", "linear"):
        for user_id, user in store.get_linear_users().items():
            name = user.get("displayName") or user.get("name") or ""
            email = user.get("email") or ""
            
            if (search in user_id.lower() or 
                search in name.lower() or 
                search in email.lower()):
                results.append({
                    "source": "linear",
                    "id": user_id,
                    "name": name,
                    "email": email,
                    "active": user.get("active", True),
                })
    
    # Search Slack users
    if source in ("both", "slack"):
        for user_id, user in store.get_slack_profiles().items():
            profile = user.get("profile", {})
            name = (
                profile.get("display_name") or
                profile.get("real_name") or
                user.get("name") or ""
            )
            email = profile.get("email") or ""
            
            if (search in user_id.lower() or 
                search in name.lower() or 
                search in email.lower()):
                results.append({
                    "source": "slack",
                    "id": user_id,
                    "name": name,
                    "display_name": profile.get("display_name"),
                    "real_name": profile.get("real_name"),
                    "email": email,
                })
    
    if not results:
        return json.dumps({
            "error": f"No users found matching '{user_id_or_name}'",
            "searched": source,
        })
    
    return json.dumps({
        "query": user_id_or_name,
        "results": results[:10],  # Limit results
    })


# --- Tool Definitions ---

MIRROR_TOOLS = [
    Tool(
        name="search_linear_issues",
        description="Search Linear issues by keyword. Supports filtering by state (e.g., 'In Progress'), assignee name, and label. Returns paginated summary results - use get_linear_issue for full details.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term to match in issue title or description. Leave empty for all issues.",
                },
                "state": {
                    "type": "string",
                    "description": "Filter by state name (e.g., 'Todo', 'In Progress', 'Done')",
                },
                "assignee": {
                    "type": "string",
                    "description": "Filter by assignee name (partial match)",
                },
                "label": {
                    "type": "string",
                    "description": "Filter by label name (partial match)",
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
            "required": [],
        },
        function=search_linear_issues,
    ),
    Tool(
        name="get_linear_issue",
        description="Get full details for a specific Linear issue by its identifier (e.g., FE-42, NIN-123). Returns description, comments, and all metadata.",
        parameters={
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "The issue identifier like FE-42, NIN-123, GTM-15",
                },
            },
            "required": ["identifier"],
        },
        function=get_linear_issue,
    ),
    Tool(
        name="list_linear_events",
        description="List recent Linear activity: state changes, assignments, comments, etc. Good for understanding what happened recently.",
        parameters={
            "type": "object",
            "properties": {
                "since_days": {
                    "type": "integer",
                    "description": "How many days back to look (default 7)",
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
        function=list_linear_events,
    ),
    Tool(
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
        function=search_slack_messages,
    ),
    Tool(
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
        function=get_slack_thread,
    ),
    Tool(
        name="lookup_user",
        description="Look up a user by ID or name to get their profile info. Works for both Linear and Slack users.",
        parameters={
            "type": "object",
            "properties": {
                "user_id_or_name": {
                    "type": "string",
                    "description": "User ID or name to search for",
                },
                "source": {
                    "type": "string",
                    "enum": ["linear", "slack", "both"],
                    "description": "Where to search: 'linear', 'slack', or 'both' (default)",
                },
            },
            "required": ["user_id_or_name"],
        },
        function=lookup_user,
    ),
]


# --- System Prompt ---

SYSTEM_PROMPT = """You are a knowledge assistant with access to your team's Linear issues and Slack conversations.

## Your Data Sources

1. **Linear Mirror**: All issues, comments, and activity events from your Linear workspace
2. **Slack Mirror**: Conversations and threads from your Slack workspace

## How to Answer Questions

1. **Search first**: Use search tools to find relevant issues or messages before answering
2. **Drill down**: Use get_linear_issue or get_slack_thread for full details when needed
3. **Synthesize**: Combine information from multiple sources to give complete answers
4. **Be transparent**: Say when information might be incomplete or outdated (mirrors sync periodically)

## Tool Strategy

- For questions about project status → search_linear_issues + get_linear_issue
- For "what happened" questions → list_linear_events
- For conversation/discussion questions → search_slack_messages + get_slack_thread
- For people questions → lookup_user

## Response Style

- Be concise but thorough
- Cite specific issues (e.g., "According to FE-42...") or threads when relevant
- If results are paginated, mention there may be more results
- If you can't find relevant information, say so clearly

Remember: You're helping someone understand their team's work. Focus on actionable insights."""


# --- Agent Factory ---

def create_mirror_agent(model_size: str = "large") -> ToolCallingAgent:
    """Create a configured mirror knowledge agent."""
    return ToolCallingAgent(
        tools=MIRROR_TOOLS,
        model_size=model_size,
        system_prompt=SYSTEM_PROMPT,
        max_tool_rounds=8,
    )


# --- CLI Entry Point ---

def main():
    """Interactive CLI for the mirror knowledge agent."""
    model_size = sys.argv[1] if len(sys.argv) > 1 else "large"
    
    print("=" * 60)
    print("🔮 Mirror Knowledge Agent")
    print("=" * 60)
    print(f"Model: Qwen {model_size}")
    print(f"Linear mirror: {LINEAR_MIRROR_DIR}")
    print(f"Slack mirror: {SLACK_MIRROR_DIR}")
    print("-" * 60)
    print("Ask questions about your Linear issues and Slack conversations.")
    print("Type 'quit' or 'exit' to stop.")
    print("=" * 60)
    print()
    
    # Verify data directories exist
    if not LINEAR_MIRROR_DIR.exists():
        print(f"⚠️  Warning: Linear mirror not found at {LINEAR_MIRROR_DIR}")
    if not SLACK_MIRROR_DIR.exists():
        print(f"⚠️  Warning: Slack mirror not found at {SLACK_MIRROR_DIR}")
    
    agent = create_mirror_agent(model_size)
    
    while True:
        try:
            user_input = input("\n💬 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n👋 Goodbye!")
            break
        
        if not user_input:
            continue
        
        if user_input.lower() in ("quit", "exit", "q"):
            print("\n👋 Goodbye!")
            break
        
        print()
        response = agent.run(user_input, verbose=True)
        
        print("\n" + "=" * 60)
        print("🤖 Assistant:")
        print("-" * 60)
        print(response)
        print("=" * 60)


if __name__ == "__main__":
    main()
