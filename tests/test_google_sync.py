"""
Tests for Google sync modules.

Tests the storage, auth, and search tools.
Note: Full sync tests require Google authentication.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


class TestStorage:
    """Tests for sync storage module."""

    def test_get_data_dir_creates_directory(self, tmp_path: Path) -> None:
        """Test that get_data_dir creates the directory if needed."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.sync.storage import get_data_dir

            data_dir = get_data_dir()
            assert data_dir.exists()
            assert data_dir.is_dir()

    def test_save_and_load_email(self, tmp_path: Path) -> None:
        """Test saving and loading an email."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.sync.storage import save_email, load_email

            email_data = {
                "id": "test123",
                "from": "sender@example.com",
                "to": ["recipient@example.com"],
                "subject": "Test Subject",
                "body_text": "Hello world",
                "date": "2024-01-15T10:00:00Z",
            }

            # Save
            path = save_email(email_data)
            assert path.exists()
            assert path.name == "test123.json"

            # Load
            loaded = load_email("test123")
            assert loaded is not None
            assert loaded["id"] == "test123"
            assert loaded["subject"] == "Test Subject"

    def test_save_and_load_calendar_event(self, tmp_path: Path) -> None:
        """Test saving and loading a calendar event."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.sync.storage import save_calendar_event, load_calendar_event

            event_data = {
                "id": "event456",
                "calendar_id": "primary",
                "summary": "Test Meeting",
                "start": "2024-01-15T10:00:00Z",
                "end": "2024-01-15T11:00:00Z",
            }

            # Save
            path = save_calendar_event(event_data)
            assert path.exists()

            # Load
            loaded = load_calendar_event("event456")
            assert loaded is not None
            assert loaded["id"] == "event456"
            assert loaded["summary"] == "Test Meeting"

    def test_save_attachment(self, tmp_path: Path) -> None:
        """Test saving an attachment."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.sync.storage import save_attachment

            content = b"PDF content here"
            path = save_attachment("email123", "document.pdf", content)

            assert path.exists()
            assert path.read_bytes() == content
            assert "email123" in str(path)

    def test_sync_state(self, tmp_path: Path) -> None:
        """Test sync state save and load."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.sync.storage import get_sync_state, save_sync_state

            # Initial state
            state = get_sync_state("gmail")
            assert state["last_sync"] is None
            assert state["email_count"] == 0

            # Update state
            state["email_count"] = 100
            state["last_history_id"] = "12345"
            save_sync_state("gmail", state)

            # Reload
            loaded = get_sync_state("gmail")
            assert loaded["email_count"] == 100
            assert loaded["last_history_id"] == "12345"
            assert loaded["last_sync"] is not None

    def test_get_storage_stats(self, tmp_path: Path) -> None:
        """Test storage statistics."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.sync.storage import (
                save_email,
                save_calendar_event,
                get_storage_stats,
            )

            # Add some data
            save_email({"id": "e1", "subject": "Test"})
            save_email({"id": "e2", "subject": "Test 2"})
            save_calendar_event({"id": "c1", "summary": "Meeting"})

            stats = get_storage_stats()
            assert stats["email_count"] == 2
            assert stats["event_count"] == 1
            assert stats["total_size_bytes"] > 0


class TestSearchEmails:
    """Tests for search_emails tool."""

    @pytest.fixture
    def mock_emails(self, tmp_path: Path) -> None:
        """Set up mock email data."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.sync.storage import save_email

            emails = [
                {
                    "id": "e1",
                    "from": "alice@example.com",
                    "to": ["bob@example.com"],
                    "subject": "Project Update",
                    "body_text": "Here is the project status update.",
                    "snippet": "Here is the project...",
                    "date": "2024-01-15T10:00:00Z",
                    "labels": ["INBOX"],
                    "attachments": [],
                },
                {
                    "id": "e2",
                    "from": "bob@example.com",
                    "to": ["alice@example.com"],
                    "subject": "Meeting Notes",
                    "body_text": "Notes from today's meeting.",
                    "snippet": "Notes from today's...",
                    "date": "2024-01-16T10:00:00Z",
                    "labels": ["INBOX"],
                    "attachments": [
                        {"filename": "notes.pdf", "path": "e2/notes.pdf", "mime_type": "application/pdf"}
                    ],
                },
                {
                    "id": "e3",
                    "from": "charlie@example.com",
                    "to": ["alice@example.com"],
                    "subject": "Invoice",
                    "body_text": "Please find attached invoice.",
                    "snippet": "Please find attached...",
                    "date": "2024-01-10T10:00:00Z",
                    "labels": ["INBOX"],
                    "attachments": [],
                },
            ]

            for email in emails:
                save_email(email)

            yield

    def test_search_by_query(self, tmp_path: Path, mock_emails: None) -> None:
        """Test searching by text query."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_emails import TOOL as search_emails_tool

            result = json.loads(search_emails_tool.execute(query="project"))
            assert result["status"] == "success"
            assert result["total"] == 1
            assert result["results"][0]["subject"] == "Project Update"

    def test_search_by_from(self, tmp_path: Path, mock_emails: None) -> None:
        """Test filtering by sender."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_emails import TOOL as search_emails_tool

            result = json.loads(search_emails_tool.execute(from_email="bob"))
            assert result["status"] == "success"
            assert result["total"] == 1
            assert result["results"][0]["from"] == "bob@example.com"

    def test_search_by_attachment(self, tmp_path: Path, mock_emails: None) -> None:
        """Test filtering by has_attachment."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_emails import TOOL as search_emails_tool

            result = json.loads(search_emails_tool.execute(has_attachment=True))
            assert result["status"] == "success"
            assert result["total"] == 1
            assert result["results"][0]["has_attachments"] is True

    def test_search_no_results(self, tmp_path: Path, mock_emails: None) -> None:
        """Test search with no matches."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_emails import TOOL as search_emails_tool

            result = json.loads(search_emails_tool.execute(query="nonexistent"))
            assert result["status"] == "success"
            assert result["total"] == 0


class TestSearchCalendar:
    """Tests for search_calendar tool."""

    @pytest.fixture
    def mock_events(self, tmp_path: Path) -> None:
        """Set up mock calendar event data."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.sync.storage import save_calendar_event

            now = datetime.now(timezone.utc)
            events = [
                {
                    "id": "ev1",
                    "calendar_id": "primary",
                    "calendar_name": "Primary",
                    "summary": "Team Standup",
                    "description": "Daily standup meeting",
                    "start": now.isoformat(),
                    "end": (now.replace(hour=now.hour + 1)).isoformat(),
                    "location": "Conference Room A",
                },
                {
                    "id": "ev2",
                    "calendar_id": "primary",
                    "calendar_name": "Primary",
                    "summary": "Lunch with Client",
                    "description": "",
                    "start": now.replace(hour=12).isoformat(),
                    "end": now.replace(hour=13).isoformat(),
                    "location": "Restaurant Downtown",
                },
            ]

            for event in events:
                save_calendar_event(event)

            yield

    def test_search_by_query(self, tmp_path: Path, mock_events: None) -> None:
        """Test searching by text query."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_calendar import TOOL as search_calendar_tool

            result = json.loads(search_calendar_tool.execute(query="standup"))
            assert result["status"] == "success"
            assert result["total"] == 1
            assert result["results"][0]["summary"] == "Team Standup"

    def test_search_by_location(self, tmp_path: Path, mock_events: None) -> None:
        """Test searching by location."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_calendar import TOOL as search_calendar_tool

            result = json.loads(search_calendar_tool.execute(query="restaurant"))
            assert result["status"] == "success"
            assert result["total"] == 1
            assert "Lunch" in result["results"][0]["summary"]


class TestGetEmail:
    """Tests for get_email tool."""

    def test_get_email_found(self, tmp_path: Path) -> None:
        """Test getting an existing email."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.sync.storage import save_email
            from daemon.tools.google.get_email import TOOL as get_email_tool

            save_email({
                "id": "test123",
                "subject": "Test Email",
                "body_text": "Full body content here.",
            })

            result = json.loads(get_email_tool.execute(email_id="test123"))
            assert result["status"] == "success"
            assert result["email"]["id"] == "test123"
            assert result["email"]["body_text"] == "Full body content here."

    def test_get_email_not_found(self, tmp_path: Path) -> None:
        """Test getting a non-existent email."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.get_email import TOOL as get_email_tool

            result = json.loads(get_email_tool.execute(email_id="nonexistent"))
            assert result["status"] == "error"
            assert "not found" in result["error"].lower()


class TestGetCalendarEvent:
    """Tests for get_calendar_event tool."""

    def test_get_event_found(self, tmp_path: Path) -> None:
        """Test getting an existing event."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.sync.storage import save_calendar_event
            from daemon.tools.google.get_calendar_event import TOOL as get_event_tool

            save_calendar_event({
                "id": "event789",
                "summary": "Test Event",
                "description": "Full event description.",
            })

            result = json.loads(get_event_tool.execute(event_id="event789"))
            assert result["status"] == "success"
            assert result["event"]["id"] == "event789"
            assert result["event"]["description"] == "Full event description."

    def test_get_event_not_found(self, tmp_path: Path) -> None:
        """Test getting a non-existent event."""
        with patch("daemon.sync.storage.DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.get_calendar_event import TOOL as get_event_tool

            result = json.loads(get_event_tool.execute(event_id="nonexistent"))
            assert result["status"] == "error"
            assert "not found" in result["error"].lower()


class TestAuth:
    """Tests for authentication module."""

    def test_is_authenticated_no_credentials(self, tmp_path: Path) -> None:
        """Test is_authenticated returns False when no credentials."""
        with patch("daemon.sync.auth.CREDENTIALS_FILE", tmp_path / "missing.json"):
            from daemon.sync.auth import is_authenticated

            assert is_authenticated() is False

    def test_get_qwen_dir_creates_directory(self, tmp_path: Path) -> None:
        """Test get_qwen_dir creates the directory."""
        with patch("daemon.sync.auth.QWEN_DIR", tmp_path / ".qwen"):
            from daemon.sync.auth import get_qwen_dir

            qwen_dir = get_qwen_dir()
            assert qwen_dir.exists()
            assert qwen_dir.is_dir()


class TestScheduler:
    """Tests for sync scheduler."""

    def test_get_sync_interval_default(self) -> None:
        """Test default sync interval."""
        with patch.dict("os.environ", {}, clear=True):
            from daemon.sync.scheduler import get_sync_interval, DEFAULT_SYNC_INTERVAL

            assert get_sync_interval() == DEFAULT_SYNC_INTERVAL

    def test_get_sync_interval_custom(self) -> None:
        """Test custom sync interval from environment."""
        with patch.dict("os.environ", {"QWEN_SYNC_INTERVAL": "600"}):
            from daemon.sync.scheduler import get_sync_interval

            assert get_sync_interval() == 600

    def test_scheduler_status(self) -> None:
        """Test scheduler status reporting."""
        from daemon.sync.scheduler import SyncScheduler

        scheduler = SyncScheduler(interval_seconds=300)
        status = scheduler.get_status()

        assert status["running"] is False
        assert status["interval_seconds"] == 300
        assert status["last_sync"] is None
