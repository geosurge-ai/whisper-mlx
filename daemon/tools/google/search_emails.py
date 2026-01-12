"""
Search emails tool.

Search locally synced emails by various criteria.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from daemon.sync.storage import load_all_emails, resolve_account

from ..base import tool

logger = logging.getLogger("qwen.tools.google")


def _parse_date(date_str: str) -> datetime | None:
    """Try to parse a date string in various formats."""
    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _email_matches_criteria(
    email: dict[str, Any],
    from_email: str | None,
    to_email: str | None,
    subject: str | None,
    query: str | None,
    after_date: str | None,
    before_date: str | None,
    has_attachments: bool | None,
    account: str | None,
) -> bool:
    """Check if an email matches the search criteria."""
    # Account filter
    if account and email.get("account", "") != account:
        return False

    # From filter (partial match)
    if from_email:
        email_from = email.get("from", "").lower()
        if from_email.lower() not in email_from:
            return False

    # To filter (partial match)
    if to_email:
        email_to = email.get("to", "").lower()
        email_cc = email.get("cc", "").lower()
        if to_email.lower() not in email_to and to_email.lower() not in email_cc:
            return False

    # Subject filter (partial match, case insensitive)
    if subject:
        email_subject = email.get("subject", "").lower()
        if subject.lower() not in email_subject:
            return False

    # Full-text query (searches subject, body, snippet)
    if query:
        query_lower = query.lower()
        searchable = " ".join([
            email.get("subject", ""),
            email.get("body", ""),
            email.get("snippet", ""),
        ]).lower()
        # Simple word matching
        if not re.search(re.escape(query_lower), searchable):
            return False

    # Date filters
    email_date_str = email.get("date", "")
    if email_date_str and (after_date or before_date):
        # Try to parse email date
        email_date = None
        # Gmail dates are often in RFC 2822 format
        try:
            from email.utils import parsedate_to_datetime
            email_date = parsedate_to_datetime(email_date_str)
        except Exception:
            pass

        if email_date:
            if after_date:
                after = _parse_date(after_date)
                if after and email_date.replace(tzinfo=None) < after:
                    return False

            if before_date:
                before = _parse_date(before_date)
                if before and email_date.replace(tzinfo=None) > before:
                    return False

    # Attachment filter
    if has_attachments is not None:
        has_att = email.get("has_attachments", False)
        if has_attachments and not has_att:
            return False
        if not has_attachments and has_att:
            return False

    return True


@tool(
    name="search_emails",
    description="""Search downloaded emails by various criteria.

Searches across all synced Gmail accounts unless a specific account is specified.
Returns matching emails with metadata and snippets.

Use this to find emails by sender, recipient, subject, content, or date range.""",
    parameters={
        "type": "object",
        "properties": {
            "account": {
                "type": "string",
                "description": "Account name to search (e.g., 'ep', 'jm'). If not specified, searches all accounts.",
            },
            "from_email": {
                "type": "string",
                "description": "Filter by sender email or name (partial match)",
            },
            "to_email": {
                "type": "string",
                "description": "Filter by recipient email (partial match, includes CC)",
            },
            "subject": {
                "type": "string",
                "description": "Filter by subject (partial match)",
            },
            "query": {
                "type": "string",
                "description": "Full-text search in subject, body, and snippet",
            },
            "after_date": {
                "type": "string",
                "description": "Only emails after this date (YYYY-MM-DD)",
            },
            "before_date": {
                "type": "string",
                "description": "Only emails before this date (YYYY-MM-DD)",
            },
            "has_attachments": {
                "type": "boolean",
                "description": "Filter by attachment presence",
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
    account: str | None = None,
    from_email: str | None = None,
    to_email: str | None = None,
    subject: str | None = None,
    query: str | None = None,
    after_date: str | None = None,
    before_date: str | None = None,
    has_attachments: bool | None = None,
    limit: int = 20,
) -> str:
    """Search downloaded emails."""
    # Resolve email address to account shortname if needed
    resolved_account = resolve_account(account) if account else None
    logger.info(f"Searching emails: account={account} (resolved={resolved_account}), from={from_email}, subject={subject}, query={query}")

    # Load all emails (optionally filtered by account)
    all_emails = load_all_emails(resolved_account)

    if not all_emails:
        return json.dumps({
            "status": "success",
            "count": 0,
            "message": "No emails found. Emails may not be synced yet.",
            "results": [],
        })

    # Filter emails
    matching: list[dict[str, Any]] = []
    for email in all_emails:
        if _email_matches_criteria(
            email,
            from_email,
            to_email,
            subject,
            query,
            after_date,
            before_date,
            has_attachments,
            resolved_account,
        ):
            # Create summary for results
            matching.append({
                "id": email.get("id", ""),
                "account": email.get("account", ""),
                "from": email.get("from", ""),
                "to": email.get("to", ""),
                "subject": email.get("subject", ""),
                "date": email.get("date", ""),
                "snippet": email.get("snippet", "")[:200],
                "has_attachments": email.get("has_attachments", False),
                "attachment_count": len(email.get("attachments", [])),
            })

    # Sort by date (newest first)
    matching.sort(key=lambda x: x.get("date", ""), reverse=True)

    # Apply limit
    results = matching[:limit]

    return json.dumps({
        "status": "success",
        "count": len(results),
        "total_matches": len(matching),
        "results": results,
    })


TOOL = search_emails
