"""
Gmail synchronization module.

Downloads emails with attachments for a specific account.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta
from typing import Any

from googleapiclient.discovery import build

from .auth import get_google_credentials
from .storage import (
    get_gmail_sync_state_file,
    list_emails,
    load_sync_state,
    save_attachment,
    save_email,
    save_sync_state,
)

logger = logging.getLogger("qwen.sync.gmail")


class GmailSyncer:
    """Syncs Gmail messages for a specific account."""

    def __init__(self, account: str, lookback_days: int = 365):
        """
        Initialize Gmail syncer.

        Args:
            account: Account name (matches credentials in ~/.qwen/accounts/{account}/)
            lookback_days: How many days back to sync (default: 1 year)
        """
        self.account = account
        self.lookback_days = lookback_days
        self.service = None
        self._existing_ids: set[str] | None = None

    def _get_service(self) -> Any:
        """Get or create Gmail API service."""
        if self.service is None:
            creds = get_google_credentials(self.account)
            if creds is None:
                raise RuntimeError(
                    f"No credentials for account '{self.account}'. "
                    f"Run: python -m daemon.sync.auth --account {self.account}"
                )
            self.service = build("gmail", "v1", credentials=creds)
        return self.service

    def _get_existing_ids(self) -> set[str]:
        """Get set of already-synced email IDs."""
        if self._existing_ids is None:
            self._existing_ids = set(list_emails(self.account))
        return self._existing_ids

    def _parse_email_headers(self, headers: list[dict[str, str]]) -> dict[str, str]:
        """Extract useful headers from email."""
        result: dict[str, str] = {}
        for header in headers:
            name = header.get("name", "").lower()
            value = header.get("value", "")
            if name in ("from", "to", "cc", "bcc", "subject", "date", "message-id"):
                result[name] = value
        return result

    def _extract_body(self, payload: dict[str, Any]) -> str:
        """Extract email body text from payload."""
        body = ""

        if "body" in payload and payload["body"].get("data"):
            try:
                data = payload["body"]["data"]
                body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception as e:
                logger.warning(f"Failed to decode body: {e}")

        # Handle multipart messages
        if "parts" in payload:
            for part in payload["parts"]:
                mime_type = part.get("mimeType", "")
                if mime_type == "text/plain" and not body:
                    if part.get("body", {}).get("data"):
                        try:
                            data = part["body"]["data"]
                            body = base64.urlsafe_b64decode(data).decode(
                                "utf-8", errors="replace"
                            )
                        except Exception:
                            pass
                elif mime_type == "text/html" and not body:
                    if part.get("body", {}).get("data"):
                        try:
                            data = part["body"]["data"]
                            body = base64.urlsafe_b64decode(data).decode(
                                "utf-8", errors="replace"
                            )
                        except Exception:
                            pass
                # Recurse into nested parts
                elif "parts" in part:
                    nested_body = self._extract_body(part)
                    if nested_body and not body:
                        body = nested_body

        return body

    def _download_attachments(
        self, message_id: str, payload: dict[str, Any]
    ) -> list[dict[str, str]]:
        """Download and save attachments from email."""
        attachments: list[dict[str, str]] = []
        service = self._get_service()

        def process_parts(parts: list[dict[str, Any]]) -> None:
            for part in parts:
                filename = part.get("filename", "")
                if filename and part.get("body", {}).get("attachmentId"):
                    try:
                        attachment_id = part["body"]["attachmentId"]
                        attachment = (
                            service.users()
                            .messages()
                            .attachments()
                            .get(
                                userId="me",
                                messageId=message_id,
                                id=attachment_id,
                            )
                            .execute()
                        )

                        data = base64.urlsafe_b64decode(attachment["data"])
                        saved_path = save_attachment(
                            self.account, message_id, filename, data
                        )

                        attachments.append(
                            {
                                "filename": filename,
                                "path": str(saved_path),
                                "size": len(data),
                                "mime_type": part.get("mimeType", ""),
                            }
                        )
                        logger.debug(f"Saved attachment: {filename}")

                    except Exception as e:
                        logger.warning(f"Failed to download attachment {filename}: {e}")

                # Recurse into nested parts
                if "parts" in part:
                    process_parts(part["parts"])

        if "parts" in payload:
            process_parts(payload["parts"])

        return attachments

    def _process_message(self, message_id: str) -> dict[str, Any] | None:
        """Fetch and process a single message."""
        service = self._get_service()

        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            payload = msg.get("payload", {})
            headers = self._parse_email_headers(payload.get("headers", []))

            # Extract body
            body = self._extract_body(payload)

            # Download attachments
            attachments = self._download_attachments(message_id, payload)

            email_data = {
                "id": message_id,
                "thread_id": msg.get("threadId", ""),
                "label_ids": msg.get("labelIds", []),
                "snippet": msg.get("snippet", ""),
                "internal_date": msg.get("internalDate", ""),
                "headers": headers,
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                "cc": headers.get("cc", ""),
                "subject": headers.get("subject", ""),
                "date": headers.get("date", ""),
                "body": body,
                "attachments": attachments,
                "has_attachments": len(attachments) > 0,
                "synced_at": datetime.utcnow().isoformat(),
            }

            return email_data

        except Exception as e:
            logger.error(f"Failed to process message {message_id}: {e}")
            return None

    def sync(self, max_results: int | None = None) -> dict[str, Any]:
        """
        Sync emails from Gmail.

        Args:
            max_results: Maximum number of emails to sync (None = no limit)

        Returns:
            Sync statistics
        """
        logger.info(f"Starting Gmail sync for account '{self.account}'...")
        service = self._get_service()

        # Load sync state
        state_file = get_gmail_sync_state_file(self.account)
        state = load_sync_state(state_file)

        # Calculate date range
        after_date = datetime.utcnow() - timedelta(days=self.lookback_days)
        query = f"after:{after_date.strftime('%Y/%m/%d')}"

        # Get existing email IDs
        existing_ids = self._get_existing_ids()

        stats = {
            "account": self.account,
            "new_emails": 0,
            "skipped": 0,
            "errors": 0,
            "attachments": 0,
        }

        try:
            # List messages
            page_token = None
            processed = 0

            while True:
                results = (
                    service.users()
                    .messages()
                    .list(
                        userId="me",
                        q=query,
                        pageToken=page_token,
                        maxResults=100,
                    )
                    .execute()
                )

                messages = results.get("messages", [])
                if not messages:
                    break

                for msg_info in messages:
                    msg_id = msg_info["id"]

                    # Skip if already synced
                    if msg_id in existing_ids:
                        stats["skipped"] += 1
                        continue

                    # Process message
                    email_data = self._process_message(msg_id)
                    if email_data:
                        save_email(self.account, email_data)
                        existing_ids.add(msg_id)
                        stats["new_emails"] += 1
                        stats["attachments"] += len(email_data.get("attachments", []))

                        if stats["new_emails"] % 10 == 0:
                            logger.info(
                                f"[{self.account}] Synced {stats['new_emails']} emails..."
                            )
                    else:
                        stats["errors"] += 1

                    processed += 1
                    if max_results and processed >= max_results:
                        break

                if max_results and processed >= max_results:
                    break

                page_token = results.get("nextPageToken")
                if not page_token:
                    break

        except Exception as e:
            logger.error(f"Gmail sync error for account '{self.account}': {e}")
            stats["error_message"] = str(e)

        # Save sync state
        state["last_sync"] = datetime.utcnow().isoformat()
        state["last_stats"] = stats
        save_sync_state(state_file, state)

        logger.info(
            f"[{self.account}] Gmail sync complete: "
            f"{stats['new_emails']} new, {stats['skipped']} skipped, "
            f"{stats['attachments']} attachments"
        )

        return stats


def sync_gmail(account: str, lookback_days: int = 365) -> dict[str, Any]:
    """
    Convenience function to sync Gmail for an account.

    Args:
        account: Account name
        lookback_days: How many days back to sync

    Returns:
        Sync statistics
    """
    syncer = GmailSyncer(account, lookback_days)
    return syncer.sync()
