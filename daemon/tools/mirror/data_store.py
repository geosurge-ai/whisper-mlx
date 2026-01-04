"""
Shared data store for mirror tools.

Provides lazy-loading access to Linear and Slack mirror data.
This module is shared across all mirror tools to avoid duplicate loading.
"""

from __future__ import annotations

import contextvars
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


# --- Configuration ---

DEFAULT_LINEAR_MIRROR = Path.home() / "Github" / "vibe-os" / "linear_mirror"
DEFAULT_SLACK_MIRROR = Path.home() / "Github" / "vibe-os" / "slack_mirror"
DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"

LINEAR_MIRROR_DIR = Path(os.environ.get("LINEAR_MIRROR_DIR", DEFAULT_LINEAR_MIRROR))
SLACK_MIRROR_DIR = Path(os.environ.get("VIBEOS_SLACK_MIRROR_DIR", DEFAULT_SLACK_MIRROR))
DATA_DIR = Path(os.environ.get("MIRROR_DATA_DIR", DEFAULT_DATA_DIR))


# --- Session Context ---

_current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_session_id", default=None
)


def set_session_context(session_id: str | None) -> contextvars.Token:
    """Set the current session context for tools. Returns a token to reset later."""
    return _current_session_id.set(session_id)


def get_session_context() -> str | None:
    """Get the current session ID, or None if not in a session context."""
    return _current_session_id.get()


def reset_session_context(token: contextvars.Token) -> None:
    """Reset the session context to its previous value."""
    _current_session_id.reset(token)


def get_session_assets_dir(session_id: str) -> Path:
    """Get the assets directory for a session, creating it if needed."""
    safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")
    assets_dir = DATA_DIR / "sessions" / safe_id / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    return assets_dir


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
    def from_dict(cls, data: dict) -> LinearIssue:
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
    def from_dict(cls, data: dict) -> LinearEvent:
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
    def from_dict(cls, data: dict) -> LinearComment:
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
    def from_dict(cls, data: dict) -> SlackMessage:
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
            for path in sorted(self.linear_dir.glob("events.*.jsonl")):
                for d in self._read_jsonl(path):
                    self._linear_events.append(LinearEvent.from_dict(d))
            self._linear_events.sort(key=lambda e: e.created_at, reverse=True)
        return self._linear_events

    def get_linear_users(self) -> dict[str, dict]:
        """Load Linear user profiles (cached)."""
        if self._linear_users is None:
            self._linear_users = {}
            users_dir = self.linear_dir / "users"
            if users_dir.exists():
                for path in users_dir.glob("*.jsonl"):
                    snapshots = self._read_jsonl_list(path)
                    if snapshots:
                        last = snapshots[-1]
                        user = last.get("user", {})
                        user_id = user.get("id", path.stem)
                        self._linear_users[user_id] = user
        return self._linear_users

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
        """Build channel ID to name mapping."""
        if self._slack_channel_names is None:
            self._slack_channel_names = {}
            convos_dir = self.slack_dir / "conversations"
            if convos_dir.exists():
                for path in convos_dir.glob("*.jsonl"):
                    channel_id = path.stem
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

    def resolve_slack_user(self, user_id: str) -> str:
        """Resolve Slack user ID to display name."""
        if not user_id:
            return "unknown"
        profiles = self.get_slack_profiles()
        if user_id in profiles:
            user = profiles[user_id]
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


# --- Global Instance ---

_data_store: MirrorDataStore | None = None


def get_data_store() -> MirrorDataStore:
    """Get or create the global data store instance."""
    global _data_store
    if _data_store is None:
        _data_store = MirrorDataStore()
    return _data_store
