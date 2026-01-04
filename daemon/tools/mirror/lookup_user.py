"""
Lookup user tool.

Look up a user by ID or name in Linear and/or Slack profiles.
"""

import json

from ..base import tool
from .data_store import get_data_store


@tool(
    name="lookup_user",
    description="Look up a user by ID or name to get their profile info. Works for both Linear and Slack users.",
    parameters={
        "type": "object",
        "properties": {
            "user_id_or_name": {
                "type": "string",
                "description": "User ID or name to search for",
            },
            "source": {
                "type": "string",
                "enum": ["linear", "slack", "both"],
                "description": "Where to search: 'linear', 'slack', or 'both' (default)",
            },
        },
        "required": ["user_id_or_name"],
    },
)
def lookup_user(user_id_or_name: str, source: str = "both") -> str:
    """Look up a user by ID or name."""
    store = get_data_store()
    results = []
    search = user_id_or_name.lower()

    # Search Linear users
    if source in ("both", "linear"):
        for user_id, user in store.get_linear_users().items():
            name = user.get("displayName") or user.get("name") or ""
            email = user.get("email") or ""

            if (
                search in user_id.lower()
                or search in name.lower()
                or search in email.lower()
            ):
                results.append({
                    "source": "linear",
                    "id": user_id,
                    "name": name,
                    "email": email,
                    "active": user.get("active", True),
                })

    # Search Slack users
    if source in ("both", "slack"):
        for user_id, user in store.get_slack_profiles().items():
            profile = user.get("profile", {})
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or user.get("name")
                or ""
            )
            email = profile.get("email") or ""

            if (
                search in user_id.lower()
                or search in name.lower()
                or search in email.lower()
            ):
                results.append({
                    "source": "slack",
                    "id": user_id,
                    "name": name,
                    "display_name": profile.get("display_name"),
                    "real_name": profile.get("real_name"),
                    "email": email,
                })

    if not results:
        return json.dumps({
            "error": f"No users found matching '{user_id_or_name}'",
            "searched": source,
        })

    return json.dumps({
        "query": user_id_or_name,
        "results": results[:10],
    })


TOOL = lookup_user
