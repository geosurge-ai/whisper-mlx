"""
Mirror tools package: Linear and Slack mirror data access tools.

Each submodule exports a TOOL constant that can be imported by profiles.
"""

# Import all tools for convenient access
from .get_current_datetime import TOOL as get_current_datetime
from .run_python import TOOL as run_python
from .search_linear_issues import TOOL as search_linear_issues
from .get_linear_issue import TOOL as get_linear_issue
from .list_linear_events import TOOL as list_linear_events
from .search_slack_messages import TOOL as search_slack_messages
from .get_slack_thread import TOOL as get_slack_thread
from .list_recent_slack_activity import TOOL as list_recent_slack_activity
from .lookup_user import TOOL as lookup_user

# All tools exported from this package
ALL_TOOLS = (
    get_current_datetime,
    run_python,
    search_linear_issues,
    get_linear_issue,
    list_linear_events,
    search_slack_messages,
    get_slack_thread,
    list_recent_slack_activity,
    lookup_user,
)

__all__ = [
    "get_current_datetime",
    "run_python",
    "search_linear_issues",
    "get_linear_issue",
    "list_linear_events",
    "search_slack_messages",
    "get_slack_thread",
    "list_recent_slack_activity",
    "lookup_user",
    "ALL_TOOLS",
]
