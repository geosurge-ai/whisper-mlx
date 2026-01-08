"""
Google OAuth2 authentication for Gmail and Calendar APIs.

Supports multiple accounts with named credentials.

Run this module directly to authenticate:
    python -m daemon.sync.auth --account myaccount

Credentials are stored in ~/.qwen/accounts/{account}/credentials.json
Client secrets can be stored in passveil (preferred) or ~/.qwen/client_secrets.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

logger = logging.getLogger("qwen.sync.auth")

# OAuth2 scopes needed for Gmail and Calendar
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# Default paths
QWEN_DIR = Path.home() / ".qwen"
ACCOUNTS_DIR = QWEN_DIR / "accounts"
CLIENT_SECRETS_FILE = QWEN_DIR / "client_secrets.json"

# Passveil key for client secrets
PASSVEIL_KEY = "google/qwen-sync-oauth"


def get_qwen_dir() -> Path:
    """Get the .qwen directory, creating it if needed."""
    QWEN_DIR.mkdir(parents=True, exist_ok=True)
    return QWEN_DIR


def get_accounts_dir() -> Path:
    """Get the accounts directory, creating it if needed."""
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    return ACCOUNTS_DIR


def get_account_dir(account: str) -> Path:
    """Get directory for a specific account."""
    account_dir = get_accounts_dir() / account
    account_dir.mkdir(parents=True, exist_ok=True)
    return account_dir


def get_credentials_file(account: str) -> Path:
    """Get credentials file path for an account."""
    return get_account_dir(account) / "credentials.json"


def _load_client_secrets_from_passveil() -> str | None:
    """
    Try to load client_secrets.json from passveil.

    Returns the path to a temp file containing the secrets, or None if not available.
    """
    try:
        result = subprocess.run(
            ["passveil", "show", PASSVEIL_KEY],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Validate it's valid JSON
            secrets = json.loads(result.stdout)
            if "installed" in secrets or "web" in secrets:
                # Write to a temp file for the OAuth library
                fd, temp_path = tempfile.mkstemp(suffix=".json", prefix="client_secrets_")
                with os.fdopen(fd, "w") as f:
                    json.dump(secrets, f)
                os.chmod(temp_path, 0o600)
                logger.debug(f"Loaded client secrets from passveil:{PASSVEIL_KEY}")
                return temp_path
    except FileNotFoundError:
        logger.debug("passveil not installed, falling back to file")
    except subprocess.TimeoutExpired:
        logger.warning("passveil timed out")
    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON in passveil:{PASSVEIL_KEY}")
    except Exception as e:
        logger.debug(f"Failed to load from passveil: {e}")

    return None


def get_client_secrets_path() -> Path | str:
    """
    Get the path to client_secrets.json.

    Priority:
    1. passveil:google/qwen-sync-oauth (preferred, returns temp file path)
    2. ~/.qwen/client_secrets.json (fallback)

    Raises FileNotFoundError if neither is available.
    """
    # Try passveil first
    passveil_path = _load_client_secrets_from_passveil()
    if passveil_path:
        return passveil_path

    # Fall back to file
    if CLIENT_SECRETS_FILE.exists():
        logger.debug(f"Using client secrets from {CLIENT_SECRETS_FILE}")
        return CLIENT_SECRETS_FILE

    # Neither available
    raise FileNotFoundError(
        f"Client secrets not found. Either:\n"
        f"  1. Store in passveil: passveil set {PASSVEIL_KEY} < client_secrets.json\n"
        f"  2. Or place at: {CLIENT_SECRETS_FILE}\n\n"
        f"See docs/AUTH.md for setup instructions."
    )


def list_accounts() -> list[str]:
    """List all configured account names."""
    accounts_dir = get_accounts_dir()
    accounts = []
    for item in accounts_dir.iterdir():
        if item.is_dir():
            creds_file = item / "credentials.json"
            if creds_file.exists():
                accounts.append(item.name)
    return sorted(accounts)


def is_authenticated(account: str | None = None) -> bool:
    """
    Check if valid Google credentials exist.

    If account is None, returns True if ANY account is authenticated.
    """
    if account is None:
        return len(list_accounts()) > 0

    creds_file = get_credentials_file(account)
    if not creds_file.exists():
        return False

    try:
        creds = get_google_credentials(account)
        return creds is not None and creds.valid
    except Exception:
        return False


def get_google_credentials(account: str) -> Credentials | None:
    """
    Get Google OAuth2 credentials for an account, refreshing if needed.

    Returns None if not authenticated (run `python -m daemon.sync.auth --account NAME` first).

    Token refresh is automatic and handles:
    - Expired access tokens (refreshes silently)
    - Expired refresh tokens (logs re-auth instructions)
    - Revoked access (logs re-auth instructions)
    """
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds_file = get_credentials_file(account)

    if not creds_file.exists():
        logger.warning(
            f"Google credentials not found for account '{account}'. "
            f"Run: python -m daemon.sync.auth --account {account}"
        )
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(creds_file), SCOPES)

        # Check if we need to refresh
        if creds and creds.expired and creds.refresh_token:
            logger.info(f"[{account}] Access token expired, refreshing...")
            try:
                creds.refresh(Request())
                # Save refreshed credentials
                _save_credentials(account, creds)
                logger.info(f"[{account}] Credentials refreshed successfully")
            except RefreshError as e:
                # Refresh token is invalid/expired
                error_msg = str(e).lower()
                if "token has been expired or revoked" in error_msg:
                    logger.error(
                        f"[{account}] Refresh token expired or revoked. "
                        f"This can happen if:\n"
                        f"  - OAuth consent is in 'Testing' mode (tokens expire after 7 days)\n"
                        f"  - User revoked access in Google account settings\n"
                        f"  - Token wasn't used for 6+ months\n"
                        f"To fix: python -m daemon.sync.auth --account {account}"
                    )
                elif "invalid_grant" in error_msg:
                    logger.error(
                        f"[{account}] Invalid grant - the authorization was revoked. "
                        f"Re-authenticate: python -m daemon.sync.auth --account {account}"
                    )
                else:
                    logger.error(
                        f"[{account}] Token refresh failed: {e}. "
                        f"Try re-authenticating: python -m daemon.sync.auth --account {account}"
                    )
                return None

        # Check if credentials are valid
        if creds and not creds.valid and not creds.refresh_token:
            logger.error(
                f"[{account}] Credentials invalid and no refresh token available. "
                f"Re-authenticate: python -m daemon.sync.auth --account {account}"
            )
            return None

        return creds

    except json.JSONDecodeError as e:
        logger.error(f"[{account}] Corrupted credentials file: {e}")
        logger.error(f"Delete {creds_file} and re-authenticate")
        return None
    except Exception as e:
        logger.error(f"[{account}] Failed to load credentials: {e}")
        return None


def _save_credentials(account: str, creds: Credentials) -> None:
    """Save credentials to file."""
    creds_file = get_credentials_file(account)
    with open(creds_file, "w") as f:
        f.write(creds.to_json())
    # Secure the file
    os.chmod(creds_file, 0o600)


def run_oauth_flow(account: str) -> Credentials:
    """
    Run the OAuth2 flow to authenticate with Google.

    Requires client_secrets.json in passveil or ~/.qwen/
    Opens a browser for user authentication.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    get_qwen_dir()

    # Get client secrets (from passveil or file)
    try:
        secrets_path = get_client_secrets_path()
    except FileNotFoundError as e:
        print(f"\n❌ {e}")
        raise

    print(f"\n🔐 Google OAuth2 Authentication for account: {account}")
    print("=" * 50)
    print("This will open a browser window for you to sign in with Google.")
    print("Required permissions: Gmail (read-only), Calendar (read-only)")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(
        str(secrets_path),
        scopes=SCOPES,
    )

    # Run local server for OAuth callback
    # access_type='offline' ensures we get a refresh token that never expires
    # prompt='consent' forces consent screen to ensure refresh token is granted
    creds = flow.run_local_server(
        port=8080,
        access_type="offline",
        prompt="consent",
        success_message="Authentication successful! You can close this window.",
    )

    # Save credentials
    _save_credentials(account, creds)

    print(f"\n✅ Authentication successful for account '{account}'!")
    print(f"   Credentials saved to: {get_credentials_file(account)}")

    return creds


def main() -> None:
    """CLI entry point for authentication."""
    import sys

    parser = argparse.ArgumentParser(
        description="Manage Google account authentication for QweN sync"
    )
    parser.add_argument(
        "--account", "-a",
        help="Account name (e.g., 'personal', 'work', 'ep', 'jm')"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all authenticated accounts"
    )

    args = parser.parse_args()

    print("\n" + "=" * 50)
    print("  QweN Google Sync - Account Management")
    print("=" * 50)

    if args.list:
        accounts = list_accounts()
        if accounts:
            print(f"\n✅ Authenticated accounts ({len(accounts)}):")
            for acc in accounts:
                print(f"   • {acc}")
        else:
            print("\n❌ No accounts configured yet.")
            print("   Run: python -m daemon.sync.auth --account NAME")
        sys.exit(0)

    if not args.account:
        print("\n❌ Please specify an account name:")
        print("   python -m daemon.sync.auth --account NAME")
        print("\nExamples:")
        print("   python -m daemon.sync.auth --account personal")
        print("   python -m daemon.sync.auth --account work")
        print("   python -m daemon.sync.auth --account ep")
        print("\nTo list existing accounts:")
        print("   python -m daemon.sync.auth --list")
        sys.exit(1)

    account = args.account

    if is_authenticated(account):
        print(f"\n✅ Account '{account}' is already authenticated!")
        print(f"   Credentials: {get_credentials_file(account)}")

        response = input("\nRe-authenticate? [y/N]: ").strip().lower()
        if response != "y":
            print("Keeping existing credentials.")
            sys.exit(0)

    try:
        run_oauth_flow(account)
    except FileNotFoundError:
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Authentication failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
