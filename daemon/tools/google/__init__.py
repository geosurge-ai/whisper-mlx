"""
Google search tools for LLM.

These tools allow the LLM to query synced Gmail and Calendar data.
"""

from .search_emails import TOOL as search_emails
from .get_email import TOOL as get_email
from .search_calendar import TOOL as search_calendar
from .get_calendar_event import TOOL as get_calendar_event

__all__ = [
    "search_emails",
    "get_email",
    "search_calendar",
    "get_calendar_event",
]
