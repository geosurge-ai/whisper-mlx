"""
Gmail sync module.

Fetches emails and attachments from Gmail API and stores them locally.
Supports incremental sync using Gmail history API.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

from googleapiclient.discovery import build

from .auth import get_google_credentials
from .storage import (
    get_sync_state,
    save_sync_state,
    save_email,
    save_attachment,
)

logger = logging.getLogger("qwen.sync.gmail")

# Default lookback period for initial sync
DEFAULT_LOOKBACK_DAYS = 365


class GmailSyncer:
    """Syncs emails from Gmail to local storage."""

    def __init__(self, lookback_days: int = DEFAULT_LOOKBACK_DAYS):
        self.lookback_days = lookback_days
        self._service = None

    def _get_service(self) -> Any:
        """Get or create Gmail API service."""
        if self._service is None:
            creds = get_google_credentials()
            if creds is None:
                raise RuntimeError(
                    "Not authenticated with Google. Run: python -m daemon.sync.auth"
                )
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    async def sync(self) -> dict[str, Any]:
        """
        Sync emails from Gmail.

        Returns dict with sync statistics.
        """
        logger.info("Starting Gmail sync...")

        service = self._get_service()
        state = get_sync_state("gmail")

        # Determine sync strategy
        if state["last_sync"] is None:
            # First sync - fetch emails from lookback period
            result = await self._full_sync(service, state)
        else:
            # Incremental sync using history API
            result = await self._incremental_sync(service, state)

        logger.info(
            f"Gmail sync complete: {result['new_emails']} new, "
            f"{result['attachments']} attachments"
        )

        return result

    async def _full_sync(
        self, service: Any, state: dict[str, Any]
    ) -> dict[str, Any]:
        """Perform full sync from scratch."""
        logger.info(f"Full Gmail sync (last {self.lookback_days} days)...")

        # Calculate date range
        after_date = datetime.now(timezone.utc) - timedelta(days=self.lookback_days)
        query = f"after:{after_date.strftime('%Y/%m/%d')}"

        new_emails = 0
        attachments_count = 0
        page_token = None
        history_id = None

        while True:
            # List messages
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

            # Fetch and store each message
            for msg_ref in messages:
                msg_id = msg_ref["id"]
                try:
                    email_data, attach_count = await self._fetch_and_store_email(
                        service, msg_id
                    )
                    new_emails += 1
                    attachments_count += attach_count

                    # Track history ID for incremental sync
                    if email_data.get("history_id"):
                        if history_id is None or int(email_data["history_id"]) > int(
                            history_id
                        ):
                            history_id = email_data["history_id"]

                except Exception as e:
                    logger.warning(f"Failed to fetch email {msg_id}: {e}")

            # Check for more pages
            page_token = results.get("nextPageToken")
            if not page_token:
                break

            logger.info(f"Synced {new_emails} emails so far...")

        # Update state
        state["last_history_id"] = history_id
        state["email_count"] = state.get("email_count", 0) + new_emails
        save_sync_state("gmail", state)

        return {
            "new_emails": new_emails,
            "attachments": attachments_count,
            "sync_type": "full",
        }

    async def _incremental_sync(
        self, service: Any, state: dict[str, Any]
    ) -> dict[str, Any]:
        """Perform incremental sync using history API."""
        history_id = state.get("last_history_id")

        if not history_id:
            # Fall back to full sync
            return await self._full_sync(service, state)

        logger.info(f"Incremental Gmail sync from history {history_id}...")

        new_emails = 0
        attachments_count = 0
        new_history_id = history_id

        try:
            page_token = None

            while True:
                # Get history changes
                results = (
                    service.users()
                    .history()
                    .list(
                        userId="me",
                        startHistoryId=history_id,
                        historyTypes=["messageAdded"],
                        pageToken=page_token,
                    )
                    .execute()
                )

                # Update history ID
                if "historyId" in results:
                    new_history_id = results["historyId"]

                history_records = results.get("history", [])

                for record in history_records:
                    messages_added = record.get("messagesAdded", [])
                    for msg_info in messages_added:
                        msg_id = msg_info["message"]["id"]
                        try:
                            _, attach_count = await self._fetch_and_store_email(
                                service, msg_id
                            )
                            new_emails += 1
                            attachments_count += attach_count
                        except Exception as e:
                            logger.warning(f"Failed to fetch email {msg_id}: {e}")

                # Check for more pages
                page_token = results.get("nextPageToken")
                if not page_token:
                    break

        except Exception as e:
            # History ID expired or invalid - fall back to full sync
            if "notFound" in str(e) or "invalid" in str(e).lower():
                logger.warning("History expired, falling back to full sync")
                return await self._full_sync(service, state)
            raise

        # Update state
        state["last_history_id"] = new_history_id
        state["email_count"] = state.get("email_count", 0) + new_emails
        save_sync_state("gmail", state)

        return {
            "new_emails": new_emails,
            "attachments": attachments_count,
            "sync_type": "incremental",
        }

    async def _fetch_and_store_email(
        self, service: Any, msg_id: str
    ) -> tuple[dict[str, Any], int]:
        """
        Fetch a single email and store it with attachments.

        Returns (email_data, attachment_count).
        """
        # Fetch full message
        message = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )

        # Parse headers
        headers = {h["name"].lower(): h["value"] for h in message["payload"]["headers"]}

        # Parse date
        date_str = headers.get("date", "")
        try:
            date = parsedate_to_datetime(date_str)
            date_iso = date.isoformat()
        except Exception:
            date_iso = None

        # Parse from/to
        from_addr = parseaddr(headers.get("from", ""))[1]
        to_addrs = [
            parseaddr(addr.strip())[1]
            for addr in headers.get("to", "").split(",")
            if addr.strip()
        ]

        # Extract body and attachments
        body_text, body_html, attachments = self._extract_body_and_attachments(
            service, msg_id, message["payload"]
        )

        # Build email data
        email_data: dict[str, Any] = {
            "id": msg_id,
            "thread_id": message.get("threadId"),
            "history_id": message.get("historyId"),
            "from": from_addr,
            "to": to_addrs,
            "subject": headers.get("subject", ""),
            "date": date_iso,
            "labels": message.get("labelIds", []),
            "snippet": message.get("snippet", ""),
            "body_text": body_text,
            "body_html": body_html,
            "attachments": attachments,
        }

        # Save email
        save_email(email_data)

        return email_data, len(attachments)

    def _extract_body_and_attachments(
        self, service: Any, msg_id: str, payload: dict[str, Any]
    ) -> tuple[str, str, list[dict[str, Any]]]:
        """
        Extract body text, HTML, and attachments from message payload.

        Returns (body_text, body_html, attachments_list).
        """
        body_text = ""
        body_html = ""
        attachments: list[dict[str, Any]] = []

        def process_part(part: dict[str, Any]) -> None:
            nonlocal body_text, body_html

            mime_type = part.get("mimeType", "")
            body = part.get("body", {})
            filename = part.get("filename", "")

            # Handle nested parts
            if "parts" in part:
                for subpart in part["parts"]:
                    process_part(subpart)
                return

            # Handle body content
            if body.get("data"):
                content = base64.urlsafe_b64decode(body["data"]).decode(
                    "utf-8", errors="replace"
                )
                if mime_type == "text/plain" and not filename:
                    body_text = content
                elif mime_type == "text/html" and not filename:
                    body_html = content

            # Handle attachments
            if filename and body.get("attachmentId"):
                try:
                    # Fetch attachment
                    attachment = (
                        service.users()
                        .messages()
                        .attachments()
                        .get(
                            userId="me",
                            messageId=msg_id,
                            id=body["attachmentId"],
                        )
                        .execute()
                    )

                    # Decode and save
                    content = base64.urlsafe_b64decode(attachment["data"])
                    path = save_attachment(msg_id, filename, content)

                    attachments.append(
                        {
                            "filename": filename,
                            "path": str(path.relative_to(path.parents[2])),
                            "mime_type": mime_type,
                            "size": len(content),
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to fetch attachment {filename}: {e}")

        process_part(payload)
        return body_text, body_html, attachments


# Singleton instance
_gmail_syncer: GmailSyncer | None = None


def get_gmail_syncer() -> GmailSyncer:
    """Get the Gmail syncer singleton."""
    global _gmail_syncer
    if _gmail_syncer is None:
        _gmail_syncer = GmailSyncer()
    return _gmail_syncer
