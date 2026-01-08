"""
Google sync modules for Gmail and Calendar.

Usage:
    # First-time setup (run once to authenticate):
    python -m daemon.sync.auth

    # Sync runs automatically in daemon background scheduler
"""

from .auth import get_google_credentials, is_authenticated
from .storage import get_data_dir, get_sync_state, save_sync_state

__all__ = [
    "get_google_credentials",
    "is_authenticated",
    "get_data_dir",
    "get_sync_state",
    "save_sync_state",
]
