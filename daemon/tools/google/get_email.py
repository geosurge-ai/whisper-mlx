"""
Get email tool.

Retrieve full content of a downloaded email by ID.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from daemon.sync.storage import list_all_accounts_with_data, load_email, resolve_account

from ..base import tool

logger = logging.getLogger("qwen.tools.google")


@tool(
    name="get_email",
    description="""Retrieve the full content of a downloaded email by its ID.

Returns complete email including body, headers, and attachment information.
Use search_emails first to find email IDs.""",
    parameters={
        "type": "object",
        "properties": {
            "email_id": {
                "type": "string",
                "description": "The email message ID (from search_emails results)",
            },
            "account": {
                "type": "string",
                "description": "Account name where the email is stored. If not specified, searches all accounts.",
            },
        },
        "required": ["email_id"],
    },
)
def get_email(
    email_id: str,
    account: str | None = None,
) -> str:
    """Get full email content by ID."""
    # Resolve email address to account shortname if needed
    resolved_account = resolve_account(account) if account else None
    logger.info(f"Getting email: id={email_id}, account={account} (resolved={resolved_account})")

    # If account specified, load directly
    if resolved_account:
        email = load_email(resolved_account, email_id)
        if email:
            return json.dumps({
                "status": "success",
                "email": _format_email(email),
            })
        return json.dumps({
            "status": "error",
            "error": f"Email {email_id} not found in account '{resolved_account}'",
        })

    # Search across all accounts
    accounts = list_all_accounts_with_data()
    for acc in accounts:
        email = load_email(acc, email_id)
        if email:
            return json.dumps({
                "status": "success",
                "email": _format_email(email),
            })

    return json.dumps({
        "status": "error",
        "error": f"Email {email_id} not found in any account",
    })


def _format_email(email: dict[str, Any]) -> dict[str, Any]:
    """Format email for response."""
    # Format attachments info
    attachments = []
    for att in email.get("attachments", []):
        attachments.append({
            "filename": att.get("filename", ""),
            "size": att.get("size", 0),
            "mime_type": att.get("mime_type", ""),
            "path": att.get("path", ""),
        })

    return {
        "id": email.get("id", ""),
        "account": email.get("account", ""),
        "thread_id": email.get("thread_id", ""),
        "from": email.get("from", ""),
        "to": email.get("to", ""),
        "cc": email.get("cc", ""),
        "subject": email.get("subject", ""),
        "date": email.get("date", ""),
        "body": email.get("body", ""),
        "snippet": email.get("snippet", ""),
        "labels": email.get("label_ids", []),
        "has_attachments": email.get("has_attachments", False),
        "attachments": attachments,
        "synced_at": email.get("synced_at", ""),
    }


TOOL = get_email
