"""
Get Linear issue details tool.

Get full details for a specific Linear issue by identifier.
"""

import json

from ..base import tool
from .data_store import get_data_store


@tool(
    name="get_linear_issue",
    description="Get full details for a specific Linear issue by its identifier (e.g., FE-42, NIN-123). Returns description, comments, and all metadata.",
    parameters={
        "type": "object",
        "properties": {
            "identifier": {
                "type": "string",
                "description": "The issue identifier like FE-42, NIN-123, GTM-15",
            },
        },
        "required": ["identifier"],
    },
)
def get_linear_issue(identifier: str) -> str:
    """Get full details for a Linear issue by identifier."""
    store = get_data_store()
    issues = store.get_linear_issues()

    issue = next((i for i in issues if i.identifier == identifier), None)
    if not issue:
        return json.dumps({"error": f"Issue {identifier} not found"})

    comments_by_issue = store.get_linear_comments()
    issue_comments = comments_by_issue.get(issue.id, [])

    issue_comments.sort(key=lambda c: c.created_at, reverse=True)
    recent_comments = issue_comments[:10]

    description = issue.description or ""
    if len(description) > 2000:
        description = description[:2000] + "...(truncated)"

    return json.dumps({
        "identifier": issue.identifier,
        "title": issue.title,
        "url": issue.url,
        "state": issue.state_name,
        "state_type": issue.state_type,
        "assignee": issue.assignee_name,
        "team": issue.team_name,
        "labels": issue.labels,
        "priority": issue.priority,
        "created_at": issue.created_at,
        "updated_at": issue.updated_at,
        "description": description,
        "comments": [
            {
                "author": c.user_name,
                "body": c.body[:500] if len(c.body) > 500 else c.body,
                "created_at": c.created_at[:10],
            }
            for c in recent_comments
        ],
    })


TOOL = get_linear_issue
