"""
Google sync modules for Gmail and Calendar.

Supports multiple accounts with separate data storage.

Usage:
    # First-time setup (run once per account):
    python -m daemon.sync.auth --account myaccount

    # List configured accounts:
    python -m daemon.sync.auth --list

    # Sync runs automatically in daemon background scheduler
"""

from .auth import (
    get_google_credentials,
    is_authenticated,
    list_accounts,
    get_account_dir,
)
from .storage import (
    get_data_dir,
    get_account_data_dir,
    load_sync_state,
    save_sync_state,
    list_all_accounts_with_data,
)

__all__ = [
    # Auth
    "get_google_credentials",
    "is_authenticated",
    "list_accounts",
    "get_account_dir",
    # Storage
    "get_data_dir",
    "get_account_data_dir",
    "load_sync_state",
    "save_sync_state",
    "list_all_accounts_with_data",
]
