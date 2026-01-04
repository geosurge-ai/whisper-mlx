"""
Search Linear issues tool.

Search Linear issues with optional filters for state, assignee, and label.
"""

import json

from ..base import tool
from .data_store import get_data_store


@tool(
    name="search_linear_issues",
    description="Search Linear issues by keyword. Supports filtering by state (e.g., 'In Progress'), assignee name, and label. Returns paginated summary results - use get_linear_issue for full details.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term to match in issue title or description. Leave empty for all issues.",
            },
            "state": {
                "type": "string",
                "description": "Filter by state name (e.g., 'Todo', 'In Progress', 'Done')",
            },
            "assignee": {
                "type": "string",
                "description": "Filter by assignee name (partial match)",
            },
            "label": {
                "type": "string",
                "description": "Filter by label name (partial match)",
            },
            "limit": {
                "type": "integer",
                "description": "Max results per page (default 10)",
            },
            "page": {
                "type": "integer",
                "description": "Page number for pagination (0-indexed)",
            },
        },
        "required": [],
    },
)
def search_linear_issues(
    query: str = "",
    state: str | None = None,
    assignee: str | None = None,
    label: str | None = None,
    limit: int = 10,
    page: int = 0,
) -> str:
    """Search Linear issues with optional filters."""
    store = get_data_store()
    issues = store.get_linear_issues()

    filtered = []
    query_lower = query.lower() if query else ""

    for issue in issues:
        if query_lower:
            title_match = query_lower in issue.title.lower()
            desc_match = issue.description and query_lower in issue.description.lower()
            if not (title_match or desc_match):
                continue

        if state and issue.state_name:
            if state.lower() not in issue.state_name.lower():
                continue

        if assignee and issue.assignee_name:
            if assignee.lower() not in issue.assignee_name.lower():
                continue
        elif assignee and not issue.assignee_name:
            continue

        if label:
            label_match = any(label.lower() in l.lower() for l in issue.labels)
            if not label_match:
                continue

        filtered.append(issue)

    filtered.sort(key=lambda i: i.updated_at, reverse=True)

    total = len(filtered)
    start = page * limit
    end = start + limit
    page_items = filtered[start:end]

    results = []
    for issue in page_items:
        results.append({
            "identifier": issue.identifier,
            "title": issue.title,
            "state": issue.state_name,
            "assignee": issue.assignee_name,
            "team": issue.team_name,
            "labels": issue.labels[:3],
            "updated_at": issue.updated_at[:10],
        })

    return json.dumps({
        "total": total,
        "page": page,
        "page_size": limit,
        "has_more": end < total,
        "issues": results,
    })


TOOL = search_linear_issues
