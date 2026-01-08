"""
Get email tool.

Retrieves full content of a specific email by ID.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..base import tool
from ...sync.storage import load_email

logger = logging.getLogger("qwen.tools.google")


@tool(
    name="get_email",
    description="""Get the full content of a specific email by ID.

Use this after search_emails to get complete email content including:
- Full body text and HTML
- Complete attachment list with file paths
- All headers and metadata

The email_id comes from search_emails results.""",
    parameters={
        "type": "object",
        "properties": {
            "email_id": {
                "type": "string",
                "description": "The email ID from search_emails results",
            },
        },
        "required": ["email_id"],
    },
)
def get_email(email_id: str) -> str:
    """Get full content of a specific email."""
    email = load_email(email_id)
    
    if email is None:
        return json.dumps({
            "status": "error",
            "error": f"Email not found: {email_id}",
        })
    
    return json.dumps({
        "status": "success",
        "email": email,
    })


TOOL = get_email
