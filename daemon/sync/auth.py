"""
Google OAuth2 authentication for Gmail and Calendar APIs.

Run this module directly to authenticate:
    python -m daemon.sync.auth

Credentials are stored in ~/.qwen/google_credentials.json
"""

from __future__ import annotations

import json
import logging
import os
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
CREDENTIALS_FILE = QWEN_DIR / "google_credentials.json"
CLIENT_SECRETS_FILE = QWEN_DIR / "client_secrets.json"


def get_qwen_dir() -> Path:
    """Get the .qwen directory, creating it if needed."""
    QWEN_DIR.mkdir(parents=True, exist_ok=True)
    return QWEN_DIR


def is_authenticated() -> bool:
    """Check if valid Google credentials exist."""
    if not CREDENTIALS_FILE.exists():
        return False

    try:
        creds = get_google_credentials()
        return creds is not None and creds.valid
    except Exception:
        return False


def get_google_credentials() -> Credentials | None:
    """
    Get Google OAuth2 credentials, refreshing if needed.

    Returns None if not authenticated (run `python -m daemon.sync.auth` first).
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not CREDENTIALS_FILE.exists():
        logger.warning(
            "Google credentials not found. Run: python -m daemon.sync.auth"
        )
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(CREDENTIALS_FILE), SCOPES)

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Google credentials...")
            creds.refresh(Request())
            # Save refreshed credentials
            _save_credentials(creds)
            logger.info("Credentials refreshed successfully")

        return creds

    except Exception as e:
        logger.error(f"Failed to load Google credentials: {e}")
        return None


def _save_credentials(creds: Credentials) -> None:
    """Save credentials to file."""
    get_qwen_dir()
    with open(CREDENTIALS_FILE, "w") as f:
        f.write(creds.to_json())
    # Secure the file
    os.chmod(CREDENTIALS_FILE, 0o600)


def run_oauth_flow() -> Credentials:
    """
    Run the OAuth2 flow to authenticate with Google.

    Requires client_secrets.json in ~/.qwen/
    Opens a browser for user authentication.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    get_qwen_dir()

    if not CLIENT_SECRETS_FILE.exists():
        print(f"\n❌ Client secrets file not found: {CLIENT_SECRETS_FILE}")
        print("\nTo set up Google OAuth2:")
        print("1. Go to https://console.cloud.google.com/apis/credentials")
        print("2. Create OAuth 2.0 Client ID (Desktop application)")
        print("3. Download the JSON and save as:")
        print(f"   {CLIENT_SECRETS_FILE}")
        print("\nThen run this command again.")
        raise FileNotFoundError(f"Missing {CLIENT_SECRETS_FILE}")

    print("\n🔐 Google OAuth2 Authentication")
    print("=" * 40)
    print("This will open a browser window for you to sign in with Google.")
    print("Required permissions: Gmail (read-only), Calendar (read-only)")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRETS_FILE),
        scopes=SCOPES,
    )

    # Run local server for OAuth callback
    creds = flow.run_local_server(
        port=8080,
        prompt="consent",
        success_message="Authentication successful! You can close this window.",
    )

    # Save credentials
    _save_credentials(creds)

    print("\n✅ Authentication successful!")
    print(f"   Credentials saved to: {CREDENTIALS_FILE}")

    return creds


def main() -> None:
    """CLI entry point for authentication."""
    import sys

    print("\n" + "=" * 50)
    print("  QweN Google Sync - Authentication Setup")
    print("=" * 50)

    if is_authenticated():
        print("\n✅ Already authenticated with Google!")
        print(f"   Credentials: {CREDENTIALS_FILE}")

        response = input("\nRe-authenticate? [y/N]: ").strip().lower()
        if response != "y":
            print("Keeping existing credentials.")
            sys.exit(0)

    try:
        run_oauth_flow()
    except FileNotFoundError:
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Authentication failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
