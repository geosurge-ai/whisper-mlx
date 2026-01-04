"""
Session persistence layer.

Stores conversation sessions as JSON files in data/sessions/.
Each session file contains the full conversation history.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# --- Data Types ---


def _empty_tool_list() -> list[dict[str, Any]]:
    return []


def _empty_message_list() -> list["SessionMessage"]:
    return []


@dataclass
class SessionMessage:
    """A single message in a session."""

    id: str
    role: str  # "user" or "assistant"
    content: str
    timestamp: float
    tool_calls: list[dict[str, Any]] = field(default_factory=_empty_tool_list)
    tool_results: list[dict[str, Any]] = field(default_factory=_empty_tool_list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionMessage:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            role=data["role"],
            content=data["content"],
            timestamp=data["timestamp"],
            tool_calls=data.get("tool_calls", []),
            tool_results=data.get("tool_results", []),
        )


@dataclass
class Session:
    """A conversation session."""

    id: str
    profile_name: str
    created_at: float
    updated_at: float
    messages: list[SessionMessage] = field(default_factory=_empty_message_list)
    title: str | None = None  # Auto-generated from first user message

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "profile_name": self.profile_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [m.to_dict() for m in self.messages],
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            profile_name=data["profile_name"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            messages=[SessionMessage.from_dict(m) for m in data.get("messages", [])],
            title=data.get("title"),
        )

    def add_message(
        self,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
    ) -> SessionMessage:
        """Add a message to the session."""
        message = SessionMessage(
            id=f"msg-{uuid.uuid4().hex[:12]}",
            role=role,
            content=content,
            timestamp=datetime.now().timestamp(),
            tool_calls=tool_calls or [],
            tool_results=tool_results or [],
        )
        self.messages.append(message)
        self.updated_at = datetime.now().timestamp()

        # Auto-generate title from first user message
        if self.title is None and role == "user" and content:
            self.title = content[:50] + ("..." if len(content) > 50 else "")

        return message


# --- Session Store ---


class SessionStore:
    """
    Persistent session storage using JSON files.

    Directory structure:
        data/sessions/{session_id}.json

    Thread-safe for single-process use (file operations are atomic enough).
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        """
        Initialize session store.

        Args:
            data_dir: Base data directory. Defaults to ./data relative to project root.
        """
        if data_dir is None:
            # Default to project_root/data
            project_root = Path(__file__).parent.parent
            data_dir = project_root / "data"

        self._data_dir = Path(data_dir)
        self._sessions_dir = self._data_dir / "sessions"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Ensure data directories exist."""
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        """Get file path for a session."""
        # Sanitize session_id to prevent path traversal
        safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return self._sessions_dir / f"{safe_id}.json"

    def create(self, profile_name: str) -> Session:
        """Create a new session."""
        now = datetime.now().timestamp()
        session = Session(
            id=f"session-{uuid.uuid4().hex[:12]}",
            profile_name=profile_name,
            created_at=now,
            updated_at=now,
            messages=[],
            title=None,
        )
        self.save(session)
        return session

    def get(self, session_id: str) -> Session | None:
        """Get a session by ID. Returns None if not found."""
        path = self._session_path(session_id)
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Session.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"Warning: Failed to load session {session_id}: {e}")
            return None

    def save(self, session: Session) -> None:
        """Save a session to disk."""
        path = self._session_path(session.id)
        # Write atomically via temp file
        temp_path = path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, indent=2)
            temp_path.replace(path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if deleted, False if not found."""
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_all(self, limit: int = 50) -> list[Session]:
        """
        List all sessions, sorted by updated_at descending.

        Args:
            limit: Maximum number of sessions to return.

        Returns:
            List of sessions, most recently updated first.
        """
        sessions: list[Session] = []

        for path in self._sessions_dir.glob("*.json"):
            session = self.get(path.stem)
            if session is not None:
                sessions.append(session)

        # Sort by updated_at descending
        sessions.sort(key=lambda s: s.updated_at, reverse=True)

        return sessions[:limit]

    def list_summaries(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        List session summaries (without full message content).

        More efficient than list_all when you only need metadata.

        Returns:
            List of dicts with id, profile_name, title, created_at, updated_at, message_count.
        """
        summaries: list[dict[str, Any]] = []

        for path in self._sessions_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                summaries.append({
                    "id": data["id"],
                    "profile_name": data["profile_name"],
                    "title": data.get("title"),
                    "created_at": data["created_at"],
                    "updated_at": data["updated_at"],
                    "message_count": len(data.get("messages", [])),
                })
            except (json.JSONDecodeError, KeyError):
                continue

        # Sort by updated_at descending
        summaries.sort(key=lambda s: s["updated_at"], reverse=True)

        return summaries[:limit]

    def prune_empty(self, max_age_seconds: float = 1800) -> int:
        """
        Delete empty sessions older than max_age_seconds.

        Args:
            max_age_seconds: Maximum age in seconds for empty sessions (default 30 min).

        Returns:
            Number of sessions deleted.
        """
        now = datetime.now().timestamp()
        deleted = 0

        for path in self._sessions_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Only prune sessions with no messages
                if len(data.get("messages", [])) == 0:
                    age = now - data["updated_at"]
                    if age > max_age_seconds:
                        path.unlink()
                        deleted += 1
            except (json.JSONDecodeError, KeyError):
                continue

        return deleted


# --- Singleton Instance ---

_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    """Get the singleton SessionStore instance."""
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
