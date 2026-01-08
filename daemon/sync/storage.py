"""
Storage helpers for Google sync data.

Data is stored in ~/.qwen/data/:
- gmail/emails/*.json - Email messages
- gmail/attachments/*/* - Email attachments
- gmail/sync_state.json - Gmail sync state
- calendar/events/*.json - Calendar events
- calendar/sync_state.json - Calendar sync state
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("qwen.sync.storage")

# Base data directory
QWEN_DIR = Path.home() / ".qwen"
DATA_DIR = QWEN_DIR / "data"


def get_data_dir() -> Path:
    """Get the data directory, creating it if needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def get_gmail_dir() -> Path:
    """Get the Gmail data directory."""
    gmail_dir = get_data_dir() / "gmail"
    gmail_dir.mkdir(parents=True, exist_ok=True)
    return gmail_dir


def get_gmail_emails_dir() -> Path:
    """Get the Gmail emails directory."""
    emails_dir = get_gmail_dir() / "emails"
    emails_dir.mkdir(parents=True, exist_ok=True)
    return emails_dir


def get_gmail_attachments_dir() -> Path:
    """Get the Gmail attachments directory."""
    attachments_dir = get_gmail_dir() / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    return attachments_dir


def get_calendar_dir() -> Path:
    """Get the Calendar data directory."""
    calendar_dir = get_data_dir() / "calendar"
    calendar_dir.mkdir(parents=True, exist_ok=True)
    return calendar_dir


def get_calendar_events_dir() -> Path:
    """Get the Calendar events directory."""
    events_dir = get_calendar_dir() / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    return events_dir


def get_sync_state(service: str) -> dict[str, Any]:
    """
    Get sync state for a service (gmail or calendar).

    Returns dict with:
    - last_sync: ISO timestamp of last successful sync
    - last_history_id: Gmail history ID for incremental sync
    - sync_tokens: Dict of calendar sync tokens
    - email_count: Number of emails synced
    - event_count: Number of events synced
    """
    if service == "gmail":
        state_file = get_gmail_dir() / "sync_state.json"
    elif service == "calendar":
        state_file = get_calendar_dir() / "sync_state.json"
    else:
        raise ValueError(f"Unknown service: {service}")

    if not state_file.exists():
        return {
            "last_sync": None,
            "last_history_id": None,
            "sync_tokens": {},
            "email_count": 0,
            "event_count": 0,
        }

    try:
        with open(state_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load sync state for {service}: {e}")
        return {
            "last_sync": None,
            "last_history_id": None,
            "sync_tokens": {},
            "email_count": 0,
            "event_count": 0,
        }


def save_sync_state(service: str, state: dict[str, Any]) -> None:
    """Save sync state for a service."""
    if service == "gmail":
        state_file = get_gmail_dir() / "sync_state.json"
    elif service == "calendar":
        state_file = get_calendar_dir() / "sync_state.json"
    else:
        raise ValueError(f"Unknown service: {service}")

    # Update last_sync timestamp
    state["last_sync"] = datetime.now(timezone.utc).isoformat()

    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)

    logger.debug(f"Saved sync state for {service}")


def save_email(email_data: dict[str, Any]) -> Path:
    """
    Save an email to disk.

    Args:
        email_data: Email data dict with id, subject, body, etc.

    Returns:
        Path to saved email JSON file.
    """
    email_id = email_data["id"]
    email_file = get_gmail_emails_dir() / f"{email_id}.json"

    with open(email_file, "w") as f:
        json.dump(email_data, f, indent=2)

    return email_file


def save_attachment(
    email_id: str, filename: str, content: bytes
) -> Path:
    """
    Save an email attachment to disk.

    Args:
        email_id: ID of the parent email
        filename: Original filename of attachment
        content: Raw attachment bytes

    Returns:
        Path to saved attachment file.
    """
    # Create directory for this email's attachments
    attachment_dir = get_gmail_attachments_dir() / email_id
    attachment_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize filename
    safe_filename = "".join(
        c if c.isalnum() or c in "._-" else "_" for c in filename
    )
    if not safe_filename:
        safe_filename = "attachment"

    attachment_path = attachment_dir / safe_filename

    # Handle duplicate filenames
    counter = 1
    original_path = attachment_path
    while attachment_path.exists():
        stem = original_path.stem
        suffix = original_path.suffix
        attachment_path = attachment_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    with open(attachment_path, "wb") as f:
        f.write(content)

    return attachment_path


def save_calendar_event(event_data: dict[str, Any]) -> Path:
    """
    Save a calendar event to disk.

    Args:
        event_data: Event data dict with id, summary, start, end, etc.

    Returns:
        Path to saved event JSON file.
    """
    event_id = event_data["id"]
    # Calendar event IDs can have special characters, sanitize
    safe_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in event_id)
    event_file = get_calendar_events_dir() / f"{safe_id}.json"

    with open(event_file, "w") as f:
        json.dump(event_data, f, indent=2)

    return event_file


def load_email(email_id: str) -> dict[str, Any] | None:
    """Load an email by ID."""
    email_file = get_gmail_emails_dir() / f"{email_id}.json"
    if not email_file.exists():
        return None

    with open(email_file) as f:
        return json.load(f)


def load_calendar_event(event_id: str) -> dict[str, Any] | None:
    """Load a calendar event by ID."""
    safe_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in event_id)
    event_file = get_calendar_events_dir() / f"{safe_id}.json"
    if not event_file.exists():
        return None

    with open(event_file) as f:
        return json.load(f)


def list_emails() -> list[Path]:
    """List all stored email files."""
    emails_dir = get_gmail_emails_dir()
    return sorted(emails_dir.glob("*.json"))


def list_calendar_events() -> list[Path]:
    """List all stored calendar event files."""
    events_dir = get_calendar_events_dir()
    return sorted(events_dir.glob("*.json"))


def get_storage_stats() -> dict[str, Any]:
    """Get statistics about stored data."""
    email_files = list_emails()
    event_files = list_calendar_events()

    # Count attachments
    attachments_dir = get_gmail_attachments_dir()
    attachment_count = sum(
        1 for f in attachments_dir.rglob("*") if f.is_file()
    )

    # Calculate total size
    total_size = 0
    for f in email_files:
        total_size += f.stat().st_size
    for f in event_files:
        total_size += f.stat().st_size
    for f in attachments_dir.rglob("*"):
        if f.is_file():
            total_size += f.stat().st_size

    return {
        "email_count": len(email_files),
        "event_count": len(event_files),
        "attachment_count": attachment_count,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
    }
