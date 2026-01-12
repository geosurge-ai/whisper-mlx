"""
Local storage management for synced Google data.

Supports multiple accounts with separate storage directories.

Storage structure:
    ~/.qwen/data/{account}/gmail/
        emails/*.json          - Individual email files
        attachments/{msg_id}/  - Email attachments
        sync_state.json        - Sync progress state
    ~/.qwen/data/{account}/calendar/
        events/*.json          - Individual event files
        sync_state.json        - Sync progress state
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("qwen.sync.storage")

# Base directories
QWEN_DIR = Path.home() / ".qwen"
DATA_DIR = QWEN_DIR / "data"

# Cache for email->account mapping
_email_to_account_cache: dict[str, str] = {}


def get_data_dir() -> Path:
    """Get the base data directory."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def _has_data(account_dir: Path) -> bool:
    """Check if an account directory has actual synced data."""
    events_dir = account_dir / "calendar" / "events"
    emails_dir = account_dir / "gmail" / "emails"

    # Check if there are any event or email files
    if events_dir.exists() and any(events_dir.glob("*.json")):
        return True
    if emails_dir.exists() and any(emails_dir.glob("*.json")):
        return True
    return False


def resolve_account(account_or_email: str) -> str:
    """
    Resolve an account shortname or email address to the actual data directory name.

    Supports:
    - Direct account shortnames (e.g., 'jm', 'ep') - returned as-is if directory exists with data
    - Full email addresses (e.g., 'user@example.com') - resolved by scanning calendar data

    Returns the account shortname to use for data access.
    """
    global _email_to_account_cache

    data_dir = get_data_dir()

    # If it's already a valid account directory with data, use it directly
    account_path = data_dir / account_or_email
    if account_path.exists() and _has_data(account_path):
        return account_or_email

    # Check cache for email resolution
    if account_or_email in _email_to_account_cache:
        return _email_to_account_cache[account_or_email]

    # Try to resolve email address by scanning calendar data for calendar_id matches
    # This handles cases like "user@example.com" -> "work"
    for item in data_dir.iterdir():
        if not item.is_dir():
            continue

        # Check calendar events for matching calendar_id
        events_dir = item / "calendar" / "events"
        if events_dir.exists():
            for event_file in events_dir.glob("*.json"):
                try:
                    with open(event_file) as f:
                        event = json.load(f)
                    calendar_id = event.get("calendar_id", "")
                    if calendar_id == account_or_email:
                        # Found a match - cache and return
                        _email_to_account_cache[account_or_email] = item.name
                        logger.debug(f"Resolved email '{account_or_email}' to account '{item.name}'")
                        return item.name
                except Exception:
                    continue

        # Also check gmail for from/to matches
        emails_dir = item / "gmail" / "emails"
        if emails_dir.exists():
            for email_file in list(emails_dir.glob("*.json"))[:10]:  # Sample first 10
                try:
                    with open(email_file) as f:
                        email = json.load(f)
                    # Check if this account's emails are from/to this address
                    from_addr = email.get("from", "")
                    if account_or_email.lower() in from_addr.lower():
                        _email_to_account_cache[account_or_email] = item.name
                        logger.debug(f"Resolved email '{account_or_email}' to account '{item.name}'")
                        return item.name
                except Exception:
                    continue

    # No resolution found - return as-is (may create empty results)
    logger.warning(f"Could not resolve account '{account_or_email}' - using as-is")
    return account_or_email


def get_account_data_dir(account: str) -> Path:
    """Get data directory for a specific account."""
    account_dir = get_data_dir() / account
    account_dir.mkdir(parents=True, exist_ok=True)
    return account_dir


# Gmail storage
def get_gmail_dir(account: str) -> Path:
    """Get Gmail data directory for an account."""
    gmail_dir = get_account_data_dir(account) / "gmail"
    gmail_dir.mkdir(parents=True, exist_ok=True)
    return gmail_dir


def get_emails_dir(account: str) -> Path:
    """Get emails directory for an account."""
    emails_dir = get_gmail_dir(account) / "emails"
    emails_dir.mkdir(parents=True, exist_ok=True)
    return emails_dir


def get_attachments_dir(account: str, message_id: str | None = None) -> Path:
    """Get attachments directory, optionally for a specific message."""
    attachments_dir = get_gmail_dir(account) / "attachments"
    if message_id:
        attachments_dir = attachments_dir / message_id
    attachments_dir.mkdir(parents=True, exist_ok=True)
    return attachments_dir


def get_gmail_sync_state_file(account: str) -> Path:
    """Get Gmail sync state file path."""
    return get_gmail_dir(account) / "sync_state.json"


# Calendar storage
def get_calendar_dir(account: str) -> Path:
    """Get Calendar data directory for an account."""
    calendar_dir = get_account_data_dir(account) / "calendar"
    calendar_dir.mkdir(parents=True, exist_ok=True)
    return calendar_dir


def get_events_dir(account: str) -> Path:
    """Get events directory for an account."""
    events_dir = get_calendar_dir(account) / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    return events_dir


def get_calendar_sync_state_file(account: str) -> Path:
    """Get Calendar sync state file path."""
    return get_calendar_dir(account) / "sync_state.json"


# Sync state management
def load_sync_state(state_file: Path) -> dict[str, Any]:
    """Load sync state from file."""
    if state_file.exists():
        try:
            with open(state_file) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load sync state: {e}")
    return {}


def save_sync_state(state_file: Path, state: dict[str, Any]) -> None:
    """Save sync state to file."""
    state["updated_at"] = datetime.utcnow().isoformat()
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


# Email storage
def save_email(account: str, email_data: dict[str, Any]) -> Path:
    """
    Save an email to storage.

    Adds account field to the email data.
    """
    message_id = email_data.get("id", "unknown")
    email_data["account"] = account

    email_file = get_emails_dir(account) / f"{message_id}.json"
    with open(email_file, "w") as f:
        json.dump(email_data, f, indent=2)

    return email_file


def load_email(account: str, message_id: str) -> dict[str, Any] | None:
    """Load an email from storage."""
    email_file = get_emails_dir(account) / f"{message_id}.json"
    if email_file.exists():
        try:
            with open(email_file) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load email {message_id}: {e}")
    return None


def list_emails(account: str) -> list[str]:
    """List all email IDs for an account."""
    emails_dir = get_emails_dir(account)
    return [f.stem for f in emails_dir.glob("*.json")]


def save_attachment(
    account: str,
    message_id: str,
    filename: str,
    data: bytes,
) -> Path:
    """Save an email attachment."""
    attachment_dir = get_attachments_dir(account, message_id)
    # Sanitize filename
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
    attachment_file = attachment_dir / safe_filename

    with open(attachment_file, "wb") as f:
        f.write(data)

    return attachment_file


# Calendar event storage
def save_event(account: str, event_data: dict[str, Any]) -> Path:
    """
    Save a calendar event to storage.

    Adds account field to the event data.
    """
    event_id = event_data.get("id", "unknown")
    event_data["account"] = account

    # Sanitize event_id for filename (Google calendar IDs can have special chars)
    safe_id = "".join(c for c in event_id if c.isalnum() or c in "_-")

    event_file = get_events_dir(account) / f"{safe_id}.json"
    with open(event_file, "w") as f:
        json.dump(event_data, f, indent=2)

    return event_file


def load_event(account: str, event_id: str) -> dict[str, Any] | None:
    """Load a calendar event from storage."""
    # Try both original and sanitized IDs
    safe_id = "".join(c for c in event_id if c.isalnum() or c in "_-")

    for eid in [event_id, safe_id]:
        event_file = get_events_dir(account) / f"{eid}.json"
        if event_file.exists():
            try:
                with open(event_file) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load event {event_id}: {e}")
    return None


def list_events(account: str) -> list[str]:
    """List all event IDs for an account."""
    events_dir = get_events_dir(account)
    return [f.stem for f in events_dir.glob("*.json")]


# Cross-account search helpers
def list_all_accounts_with_data() -> list[str]:
    """List all accounts that have synced data."""
    data_dir = get_data_dir()
    accounts = []
    for item in data_dir.iterdir():
        if item.is_dir():
            # Check if it has gmail or calendar data
            if (item / "gmail").exists() or (item / "calendar").exists():
                accounts.append(item.name)
    return sorted(accounts)


def load_all_emails(account: str | None = None) -> list[dict[str, Any]]:
    """
    Load all emails, optionally filtered by account.

    If account is None, loads from all accounts.
    Supports both account shortnames (e.g., 'work') and email addresses (e.g., 'user@example.com').
    """
    emails: list[dict[str, Any]] = []

    if account:
        # Resolve email address to account shortname if needed
        resolved_account = resolve_account(account)
        accounts = [resolved_account]
    else:
        accounts = list_all_accounts_with_data()

    for acc in accounts:
        emails_dir = get_emails_dir(acc)
        for email_file in emails_dir.glob("*.json"):
            try:
                with open(email_file) as f:
                    email = json.load(f)
                    # Ensure account field is set
                    email["account"] = acc
                    emails.append(email)
            except Exception as e:
                logger.warning(f"Failed to load email {email_file}: {e}")

    return emails


def load_all_events(account: str | None = None) -> list[dict[str, Any]]:
    """
    Load all calendar events, optionally filtered by account.

    If account is None, loads from all accounts.
    Supports both account shortnames (e.g., 'work') and email addresses (e.g., 'user@example.com').
    """
    events: list[dict[str, Any]] = []

    if account:
        # Resolve email address to account shortname if needed
        resolved_account = resolve_account(account)
        accounts = [resolved_account]
    else:
        accounts = list_all_accounts_with_data()

    for acc in accounts:
        events_dir = get_events_dir(acc)
        for event_file in events_dir.glob("*.json"):
            try:
                with open(event_file) as f:
                    event = json.load(f)
                    # Ensure account field is set
                    event["account"] = acc
                    events.append(event)
            except Exception as e:
                logger.warning(f"Failed to load event {event_file}: {e}")

    return events


def get_storage_stats(account: str | None = None) -> dict[str, Any]:
    """Get storage statistics for an account or all accounts."""
    if account:
        accounts = [account]
    else:
        accounts = list_all_accounts_with_data()

    stats: dict[str, Any] = {
        "accounts": {},
        "total_emails": 0,
        "total_events": 0,
    }

    for acc in accounts:
        email_count = len(list_emails(acc))
        event_count = len(list_events(acc))

        stats["accounts"][acc] = {
            "emails": email_count,
            "events": event_count,
        }
        stats["total_emails"] += email_count
        stats["total_events"] += event_count

    return stats
