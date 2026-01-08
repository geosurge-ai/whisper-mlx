"""
Tests for Google sync modules with multi-account support.

Tests the storage, auth, and search tools.
Note: Full sync tests require Google authentication.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Import modules first so patch() can find the attributes
import daemon.sync.storage as storage_module
import daemon.sync.auth as auth_module


class TestStorage:
    """Tests for sync storage module with multi-account support."""

    def test_get_data_dir_creates_directory(self, tmp_path: Path) -> None:
        """Test that get_data_dir creates the directory if needed."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            data_dir = storage_module.get_data_dir()
            assert data_dir.exists()
            assert data_dir.is_dir()

    def test_get_account_data_dir_creates_directory(self, tmp_path: Path) -> None:
        """Test that get_account_data_dir creates per-account directories."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            ep_dir = storage_module.get_account_data_dir("ep")
            jm_dir = storage_module.get_account_data_dir("jm")

            assert ep_dir.exists()
            assert jm_dir.exists()
            assert ep_dir.name == "ep"
            assert jm_dir.name == "jm"

    def test_save_and_load_email_with_account(self, tmp_path: Path) -> None:
        """Test saving and loading an email with account parameter."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            email_data = {
                "id": "test123",
                "from": "sender@example.com",
                "to": "recipient@example.com",
                "subject": "Test Subject",
                "body": "Hello world",
                "date": "2024-01-15T10:00:00Z",
            }

            # Save to ep account
            path = storage_module.save_email("ep", email_data)
            assert path.exists()
            assert path.name == "test123.json"
            assert "ep" in str(path)

            # Load from ep account
            loaded = storage_module.load_email("ep", "test123")
            assert loaded is not None
            assert loaded["id"] == "test123"
            assert loaded["subject"] == "Test Subject"
            assert loaded["account"] == "ep"

            # Should not be found in jm account
            not_found = storage_module.load_email("jm", "test123")
            assert not_found is None

    def test_save_and_load_event_with_account(self, tmp_path: Path) -> None:
        """Test saving and loading a calendar event with account parameter."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            event_data = {
                "id": "event456",
                "calendar_id": "primary",
                "summary": "Test Meeting",
                "start": "2024-01-15T10:00:00Z",
                "end": "2024-01-15T11:00:00Z",
            }

            # Save to jm account
            path = storage_module.save_event("jm", event_data)
            assert path.exists()
            assert "jm" in str(path)

            # Load from jm account
            loaded = storage_module.load_event("jm", "event456")
            assert loaded is not None
            assert loaded["id"] == "event456"
            assert loaded["summary"] == "Test Meeting"
            assert loaded["account"] == "jm"

    def test_save_attachment_with_account(self, tmp_path: Path) -> None:
        """Test saving an attachment with account parameter."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            content = b"PDF content here"
            path = storage_module.save_attachment("ep", "email123", "document.pdf", content)

            assert path.exists()
            assert path.read_bytes() == content
            assert "ep" in str(path)
            assert "email123" in str(path)

    def test_list_all_accounts_with_data(self, tmp_path: Path) -> None:
        """Test listing all accounts with synced data."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            # No accounts initially
            accounts = storage_module.list_all_accounts_with_data()
            assert accounts == []

            # Add data to ep account
            storage_module.save_email("ep", {"id": "e1", "subject": "Test"})
            accounts = storage_module.list_all_accounts_with_data()
            assert accounts == ["ep"]

            # Add data to jm account
            storage_module.save_event("jm", {"id": "ev1", "summary": "Meeting"})
            accounts = storage_module.list_all_accounts_with_data()
            assert sorted(accounts) == ["ep", "jm"]

    def test_load_all_emails_across_accounts(self, tmp_path: Path) -> None:
        """Test loading emails from all accounts."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            # Save emails to different accounts
            storage_module.save_email("ep", {"id": "e1", "subject": "EP Email"})
            storage_module.save_email("jm", {"id": "e2", "subject": "JM Email"})
            storage_module.save_email("ep", {"id": "e3", "subject": "EP Email 2"})

            # Load all
            all_emails = storage_module.load_all_emails()
            assert len(all_emails) == 3

            # Load only ep
            ep_emails = storage_module.load_all_emails("ep")
            assert len(ep_emails) == 2
            assert all(e["account"] == "ep" for e in ep_emails)

            # Load only jm
            jm_emails = storage_module.load_all_emails("jm")
            assert len(jm_emails) == 1
            assert jm_emails[0]["account"] == "jm"

    def test_load_all_events_across_accounts(self, tmp_path: Path) -> None:
        """Test loading events from all accounts."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            # Save events to different accounts
            storage_module.save_event("ep", {"id": "ev1", "summary": "EP Meeting"})
            storage_module.save_event("jm", {"id": "ev2", "summary": "JM Meeting"})

            # Load all
            all_events = storage_module.load_all_events()
            assert len(all_events) == 2

            # Load only jm
            jm_events = storage_module.load_all_events("jm")
            assert len(jm_events) == 1
            assert jm_events[0]["account"] == "jm"

    def test_get_storage_stats_multi_account(self, tmp_path: Path) -> None:
        """Test storage statistics across accounts."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            # Add data
            storage_module.save_email("ep", {"id": "e1", "subject": "Test"})
            storage_module.save_email("ep", {"id": "e2", "subject": "Test 2"})
            storage_module.save_event("ep", {"id": "ev1", "summary": "Meeting"})
            storage_module.save_event("jm", {"id": "ev2", "summary": "Meeting"})

            # Stats for all
            stats = storage_module.get_storage_stats()
            assert stats["total_emails"] == 2
            assert stats["total_events"] == 2
            assert "ep" in stats["accounts"]
            assert "jm" in stats["accounts"]
            assert stats["accounts"]["ep"]["emails"] == 2
            assert stats["accounts"]["ep"]["events"] == 1
            assert stats["accounts"]["jm"]["emails"] == 0
            assert stats["accounts"]["jm"]["events"] == 1

            # Stats for ep only
            ep_stats = storage_module.get_storage_stats("ep")
            assert ep_stats["total_emails"] == 2
            assert ep_stats["total_events"] == 1


class TestSearchEmails:
    """Tests for search_emails tool with multi-account support."""

    @pytest.fixture
    def mock_emails(self, tmp_path: Path) -> None:
        """Set up mock email data across accounts."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            # EP account emails
            storage_module.save_email("ep", {
                "id": "e1",
                "from": "alice@example.com",
                "to": "bob@example.com",
                "subject": "Project Update",
                "body": "Here is the project status update.",
                "snippet": "Here is the project...",
                "date": "Mon, 15 Jan 2024 10:00:00 +0000",
                "has_attachments": False,
                "attachments": [],
            })

            storage_module.save_email("ep", {
                "id": "e2",
                "from": "bob@example.com",
                "to": "alice@example.com",
                "subject": "Meeting Notes",
                "body": "Notes from today's meeting.",
                "snippet": "Notes from today's...",
                "date": "Tue, 16 Jan 2024 10:00:00 +0000",
                "has_attachments": True,
                "attachments": [
                    {"filename": "notes.pdf", "path": "e2/notes.pdf", "mime_type": "application/pdf"}
                ],
            })

            # JM account emails
            storage_module.save_email("jm", {
                "id": "e3",
                "from": "charlie@example.com",
                "to": "alice@example.com",
                "subject": "Invoice",
                "body": "Please find attached invoice.",
                "snippet": "Please find attached...",
                "date": "Wed, 10 Jan 2024 10:00:00 +0000",
                "has_attachments": False,
                "attachments": [],
            })

            yield

    def test_search_all_accounts(self, tmp_path: Path, mock_emails: None) -> None:
        """Test searching across all accounts."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_emails import TOOL as search_emails_tool

            result = json.loads(search_emails_tool.execute())
            assert result["status"] == "success"
            assert result["total_matches"] == 3

    def test_search_by_account(self, tmp_path: Path, mock_emails: None) -> None:
        """Test filtering by account."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_emails import TOOL as search_emails_tool

            # Search EP account only
            result = json.loads(search_emails_tool.execute(account="ep"))
            assert result["status"] == "success"
            assert result["total_matches"] == 2
            assert all(r["account"] == "ep" for r in result["results"])

            # Search JM account only
            result = json.loads(search_emails_tool.execute(account="jm"))
            assert result["status"] == "success"
            assert result["total_matches"] == 1
            assert result["results"][0]["account"] == "jm"

    def test_search_by_query(self, tmp_path: Path, mock_emails: None) -> None:
        """Test searching by text query."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_emails import TOOL as search_emails_tool

            result = json.loads(search_emails_tool.execute(query="project"))
            assert result["status"] == "success"
            assert result["total_matches"] == 1
            assert result["results"][0]["subject"] == "Project Update"

    def test_search_by_from(self, tmp_path: Path, mock_emails: None) -> None:
        """Test filtering by sender."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_emails import TOOL as search_emails_tool

            result = json.loads(search_emails_tool.execute(from_email="bob"))
            assert result["status"] == "success"
            assert result["total_matches"] == 1
            assert result["results"][0]["from"] == "bob@example.com"

    def test_search_by_attachment(self, tmp_path: Path, mock_emails: None) -> None:
        """Test filtering by has_attachments."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_emails import TOOL as search_emails_tool

            result = json.loads(search_emails_tool.execute(has_attachments=True))
            assert result["status"] == "success"
            assert result["total_matches"] == 1
            assert result["results"][0]["has_attachments"] is True


class TestSearchCalendar:
    """Tests for search_calendar tool with multi-account support."""

    @pytest.fixture
    def mock_events(self, tmp_path: Path) -> None:
        """Set up mock calendar event data across accounts."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            now = datetime.now(timezone.utc)

            # EP account events
            storage_module.save_event("ep", {
                "id": "ev1",
                "calendar_id": "primary",
                "calendar_name": "Primary",
                "summary": "Team Standup",
                "description": "Daily standup meeting",
                "start": now.isoformat(),
                "end": now.replace(hour=(now.hour + 1) % 24).isoformat(),
                "location": "Conference Room A",
            })

            # JM account events
            storage_module.save_event("jm", {
                "id": "ev2",
                "calendar_id": "primary",
                "calendar_name": "Primary",
                "summary": "Lunch with Client",
                "description": "",
                "start": now.replace(hour=12).isoformat(),
                "end": now.replace(hour=13).isoformat(),
                "location": "Restaurant Downtown",
            })

            yield

    def test_search_all_accounts(self, tmp_path: Path, mock_events: None) -> None:
        """Test searching across all accounts."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_calendar import TOOL as search_calendar_tool

            result = json.loads(search_calendar_tool.execute())
            assert result["status"] == "success"
            assert result["total_matches"] == 2

    def test_search_by_account(self, tmp_path: Path, mock_events: None) -> None:
        """Test filtering by account."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_calendar import TOOL as search_calendar_tool

            # Search EP only
            result = json.loads(search_calendar_tool.execute(account="ep"))
            assert result["status"] == "success"
            assert result["total_matches"] == 1
            assert result["results"][0]["account"] == "ep"

    def test_search_by_query(self, tmp_path: Path, mock_events: None) -> None:
        """Test searching by text query."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_calendar import TOOL as search_calendar_tool

            result = json.loads(search_calendar_tool.execute(query="standup"))
            assert result["status"] == "success"
            assert result["total_matches"] == 1
            assert result["results"][0]["summary"] == "Team Standup"

    def test_search_by_location(self, tmp_path: Path, mock_events: None) -> None:
        """Test searching by location."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.search_calendar import TOOL as search_calendar_tool

            result = json.loads(search_calendar_tool.execute(query="restaurant"))
            assert result["status"] == "success"
            assert result["total_matches"] == 1
            assert "Lunch" in result["results"][0]["summary"]


class TestGetEmail:
    """Tests for get_email tool with multi-account support."""

    def test_get_email_with_account(self, tmp_path: Path) -> None:
        """Test getting an email with account specified."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.get_email import TOOL as get_email_tool

            storage_module.save_email("ep", {
                "id": "test123",
                "subject": "Test Email",
                "body": "Full body content here.",
            })

            result = json.loads(get_email_tool.execute(email_id="test123", account="ep"))
            assert result["status"] == "success"
            assert result["email"]["id"] == "test123"
            assert result["email"]["body"] == "Full body content here."
            assert result["email"]["account"] == "ep"

    def test_get_email_search_all_accounts(self, tmp_path: Path) -> None:
        """Test getting email searches across all accounts when account not specified."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.get_email import TOOL as get_email_tool

            storage_module.save_email("jm", {
                "id": "hidden123",
                "subject": "Hidden Email",
                "body": "Found it!",
            })

            # Without specifying account
            result = json.loads(get_email_tool.execute(email_id="hidden123"))
            assert result["status"] == "success"
            assert result["email"]["account"] == "jm"

    def test_get_email_not_found(self, tmp_path: Path) -> None:
        """Test getting a non-existent email."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.get_email import TOOL as get_email_tool

            result = json.loads(get_email_tool.execute(email_id="nonexistent"))
            assert result["status"] == "error"
            assert "not found" in result["error"].lower()


class TestGetCalendarEvent:
    """Tests for get_calendar_event tool with multi-account support."""

    def test_get_event_with_account(self, tmp_path: Path) -> None:
        """Test getting an event with account specified."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.get_calendar_event import TOOL as get_event_tool

            storage_module.save_event("jm", {
                "id": "event789",
                "summary": "Test Event",
                "description": "Full event description.",
            })

            result = json.loads(get_event_tool.execute(event_id="event789", account="jm"))
            assert result["status"] == "success"
            assert result["event"]["id"] == "event789"
            assert result["event"]["description"] == "Full event description."
            assert result["event"]["account"] == "jm"

    def test_get_event_search_all_accounts(self, tmp_path: Path) -> None:
        """Test getting event searches across all accounts when account not specified."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.get_calendar_event import TOOL as get_event_tool

            storage_module.save_event("ep", {
                "id": "secret_event",
                "summary": "Secret Meeting",
            })

            # Without specifying account
            result = json.loads(get_event_tool.execute(event_id="secret_event"))
            assert result["status"] == "success"
            assert result["event"]["account"] == "ep"

    def test_get_event_not_found(self, tmp_path: Path) -> None:
        """Test getting a non-existent event."""
        with patch.object(storage_module, "DATA_DIR", tmp_path / "data"):
            from daemon.tools.google.get_calendar_event import TOOL as get_event_tool

            result = json.loads(get_event_tool.execute(event_id="nonexistent"))
            assert result["status"] == "error"
            assert "not found" in result["error"].lower()


class TestAuth:
    """Tests for authentication module with multi-account support."""

    def test_is_authenticated_no_accounts(self, tmp_path: Path) -> None:
        """Test is_authenticated returns False when no accounts configured."""
        with patch.object(auth_module, "ACCOUNTS_DIR", tmp_path / "accounts"):
            assert auth_module.is_authenticated() is False

    def test_is_authenticated_specific_account(self, tmp_path: Path) -> None:
        """Test is_authenticated for a specific account."""
        with patch.object(auth_module, "ACCOUNTS_DIR", tmp_path / "accounts"):
            assert auth_module.is_authenticated("ep") is False
            assert auth_module.is_authenticated("jm") is False

    def test_list_accounts_empty(self, tmp_path: Path) -> None:
        """Test list_accounts returns empty list when no accounts."""
        with patch.object(auth_module, "ACCOUNTS_DIR", tmp_path / "accounts"):
            accounts = auth_module.list_accounts()
            assert accounts == []

    def test_get_account_dir_creates_directory(self, tmp_path: Path) -> None:
        """Test get_account_dir creates per-account directories."""
        with patch.object(auth_module, "ACCOUNTS_DIR", tmp_path / "accounts"):
            ep_dir = auth_module.get_account_dir("ep")
            assert ep_dir.exists()
            assert ep_dir.name == "ep"

    def test_get_qwen_dir_creates_directory(self, tmp_path: Path) -> None:
        """Test get_qwen_dir creates the directory."""
        with patch.object(auth_module, "QWEN_DIR", tmp_path / ".qwen"):
            qwen_dir = auth_module.get_qwen_dir()
            assert qwen_dir.exists()
            assert qwen_dir.is_dir()


class TestScheduler:
    """Tests for sync scheduler with multi-account support."""

    def test_sync_interval_constant(self) -> None:
        """Test sync interval is defined."""
        from daemon.sync.scheduler import SYNC_INTERVAL_SECONDS

        assert SYNC_INTERVAL_SECONDS == 5 * 60  # 5 minutes

    def test_lookback_days_constant(self) -> None:
        """Test lookback days is defined."""
        from daemon.sync.scheduler import LOOKBACK_DAYS

        assert LOOKBACK_DAYS == 365  # 1 year
