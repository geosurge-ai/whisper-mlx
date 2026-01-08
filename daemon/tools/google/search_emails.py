"""
Search emails tool.

Searches through synced Gmail messages.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..base import tool
from ...sync.storage import get_gmail_emails_dir, list_emails

logger = logging.getLogger("qwen.tools.google")


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse ISO date string to datetime."""
    if not date_str:
        return None
    try:
        # Handle various ISO formats
        if date_str.endswith("Z"):
            date_str = date_str[:-1] + "+00:00"
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def _matches_query(email: dict[str, Any], query: str) -> bool:
    """Check if email matches text query."""
    query_lower = query.lower()
    
    # Search in subject, body, from, and snippet
    searchable = [
        email.get("subject", ""),
        email.get("body_text", ""),
        email.get("from", ""),
        email.get("snippet", ""),
    ]
    
    for field in searchable:
        if query_lower in field.lower():
            return True
    
    return False


def _matches_from(email: dict[str, Any], from_email: str) -> bool:
    """Check if email is from specified address."""
    email_from = email.get("from", "").lower()
    return from_email.lower() in email_from


def _matches_subject(email: dict[str, Any], subject: str) -> bool:
    """Check if email subject contains text."""
    email_subject = email.get("subject", "").lower()
    return subject.lower() in email_subject


def _in_date_range(
    email: dict[str, Any],
    after: str | None,
    before: str | None,
) -> bool:
    """Check if email is within date range."""
    email_date = _parse_date(email.get("date"))
    if not email_date:
        return True  # Include emails without dates
    
    if after:
        after_date = _parse_date(after)
        if after_date and email_date < after_date:
            return False
    
    if before:
        before_date = _parse_date(before)
        if before_date and email_date > before_date:
            return False
    
    return True


def _has_attachments(email: dict[str, Any]) -> bool:
    """Check if email has attachments."""
    return len(email.get("attachments", [])) > 0


@tool(
    name="search_emails",
    description="""Search through synced Gmail messages.

Use this tool to find emails by:
- Text search (subject, body, sender)
- Sender email address
- Subject line
- Date range
- Attachments

Returns a list of matching emails with snippets. Use get_email to get full content.""",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text to search for in subject, body, and sender",
            },
            "from_email": {
                "type": "string",
                "description": "Filter by sender email address (partial match)",
            },
            "subject": {
                "type": "string",
                "description": "Filter by subject line (partial match)",
            },
            "after": {
                "type": "string",
                "description": "Only emails after this date (ISO format: 2024-01-15)",
            },
            "before": {
                "type": "string",
                "description": "Only emails before this date (ISO format: 2024-01-15)",
            },
            "has_attachment": {
                "type": "boolean",
                "description": "If true, only return emails with attachments",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results (default: 20)",
            },
        },
        "required": [],
    },
)
def search_emails(
    query: str = "",
    from_email: str = "",
    subject: str = "",
    after: str = "",
    before: str = "",
    has_attachment: bool = False,
    limit: int = 20,
) -> str:
    """Search through synced Gmail messages."""
    emails_dir = get_gmail_emails_dir()
    email_files = list_emails()
    
    if not email_files:
        return json.dumps({
            "status": "success",
            "message": "No emails synced yet. Sync will run automatically.",
            "results": [],
            "total": 0,
        })
    
    results: list[dict[str, Any]] = []
    
    for email_file in email_files:
        try:
            with open(email_file) as f:
                email = json.load(f)
            
            # Apply filters
            if query and not _matches_query(email, query):
                continue
            if from_email and not _matches_from(email, from_email):
                continue
            if subject and not _matches_subject(email, subject):
                continue
            if not _in_date_range(email, after or None, before or None):
                continue
            if has_attachment and not _has_attachments(email):
                continue
            
            # Build result summary
            results.append({
                "id": email["id"],
                "from": email.get("from", ""),
                "to": email.get("to", []),
                "subject": email.get("subject", "(No subject)"),
                "date": email.get("date", ""),
                "snippet": email.get("snippet", "")[:200],
                "has_attachments": _has_attachments(email),
                "attachment_count": len(email.get("attachments", [])),
                "labels": email.get("labels", []),
            })
            
            if len(results) >= limit:
                break
                
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read email {email_file}: {e}")
            continue
    
    # Sort by date (newest first)
    results.sort(key=lambda x: x.get("date", ""), reverse=True)
    
    return json.dumps({
        "status": "success",
        "results": results,
        "total": len(results),
        "limit": limit,
    })


TOOL = search_emails
