"""
Google Calendar synchronization module.

Downloads calendar events for a specific account.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build

from .auth import get_google_credentials
from .storage import (
    get_calendar_sync_state_file,
    list_events,
    load_sync_state,
    save_event,
    save_sync_state,
)

logger = logging.getLogger("qwen.sync.calendar")


class CalendarSyncer:
    """Syncs Google Calendar events for a specific account."""

    def __init__(self, account: str, lookback_days: int = 365, lookahead_days: int = 365):
        """
        Initialize Calendar syncer.

        Args:
            account: Account name (matches credentials in ~/.qwen/accounts/{account}/)
            lookback_days: How many days back to sync (default: 1 year)
            lookahead_days: How many days forward to sync (default: 1 year)
        """
        self.account = account
        self.lookback_days = lookback_days
        self.lookahead_days = lookahead_days
        self.service = None
        self._existing_ids: set[str] | None = None

    def _get_service(self) -> Any:
        """Get or create Calendar API service."""
        if self.service is None:
            creds = get_google_credentials(self.account)
            if creds is None:
                raise RuntimeError(
                    f"No credentials for account '{self.account}'. "
                    f"Run: python -m daemon.sync.auth --account {self.account}"
                )
            self.service = build("calendar", "v3", credentials=creds)
        return self.service

    def _get_existing_ids(self) -> set[str]:
        """Get set of already-synced event IDs."""
        if self._existing_ids is None:
            self._existing_ids = set(list_events(self.account))
        return self._existing_ids

    def _parse_datetime(self, dt_info: dict[str, str]) -> str:
        """Parse datetime from event start/end."""
        if "dateTime" in dt_info:
            return dt_info["dateTime"]
        elif "date" in dt_info:
            return dt_info["date"]
        return ""

    def _process_event(self, event: dict[str, Any], calendar_id: str) -> dict[str, Any]:
        """Process a calendar event into our format."""
        start = event.get("start", {})
        end = event.get("end", {})

        # Handle attendees
        attendees = []
        for att in event.get("attendees", []):
            attendees.append({
                "email": att.get("email", ""),
                "display_name": att.get("displayName", ""),
                "response_status": att.get("responseStatus", ""),
                "organizer": att.get("organizer", False),
                "self": att.get("self", False),
            })

        event_data = {
            "id": event.get("id", ""),
            "calendar_id": calendar_id,
            "summary": event.get("summary", "(No title)"),
            "description": event.get("description", ""),
            "location": event.get("location", ""),
            "start": self._parse_datetime(start),
            "end": self._parse_datetime(end),
            "all_day": "date" in start,
            "timezone": start.get("timeZone", ""),
            "status": event.get("status", ""),
            "created": event.get("created", ""),
            "updated": event.get("updated", ""),
            "creator": event.get("creator", {}),
            "organizer": event.get("organizer", {}),
            "attendees": attendees,
            "recurring_event_id": event.get("recurringEventId", ""),
            "html_link": event.get("htmlLink", ""),
            "conference_data": event.get("conferenceData", {}),
            "reminders": event.get("reminders", {}),
            "synced_at": datetime.utcnow().isoformat(),
        }

        return event_data

    def _sync_calendar(
        self,
        calendar_id: str,
        calendar_name: str,
        time_min: str,
        time_max: str,
        existing_ids: set[str],
    ) -> dict[str, int]:
        """Sync events from a single calendar."""
        service = self._get_service()
        stats = {"new": 0, "skipped": 0, "errors": 0}

        try:
            page_token = None

            while True:
                events_result = (
                    service.events()
                    .list(
                        calendarId=calendar_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True,  # Expand recurring events
                        orderBy="startTime",
                        pageToken=page_token,
                        maxResults=250,
                    )
                    .execute()
                )

                events = events_result.get("items", [])

                for event in events:
                    event_id = event.get("id", "")

                    # Create composite ID for uniqueness across calendars
                    safe_id = "".join(c for c in event_id if c.isalnum() or c in "_-")

                    if safe_id in existing_ids:
                        stats["skipped"] += 1
                        continue

                    try:
                        event_data = self._process_event(event, calendar_id)
                        event_data["calendar_name"] = calendar_name
                        save_event(self.account, event_data)
                        existing_ids.add(safe_id)
                        stats["new"] += 1
                    except Exception as e:
                        logger.warning(f"Failed to save event {event_id}: {e}")
                        stats["errors"] += 1

                page_token = events_result.get("nextPageToken")
                if not page_token:
                    break

        except Exception as e:
            logger.error(f"Failed to sync calendar {calendar_name}: {e}")
            stats["errors"] += 1

        return stats

    def sync(self) -> dict[str, Any]:
        """
        Sync events from all calendars.

        Returns:
            Sync statistics
        """
        logger.info(f"Starting Calendar sync for account '{self.account}'...")
        service = self._get_service()

        # Load sync state
        state_file = get_calendar_sync_state_file(self.account)
        state = load_sync_state(state_file)

        # Calculate time range
        now = datetime.now(timezone.utc)
        time_min = (now - timedelta(days=self.lookback_days)).isoformat()
        time_max = (now + timedelta(days=self.lookahead_days)).isoformat()

        # Get existing event IDs
        existing_ids = self._get_existing_ids()

        stats: dict[str, Any] = {
            "account": self.account,
            "calendars_synced": 0,
            "new_events": 0,
            "skipped": 0,
            "errors": 0,
            "calendars": {},
        }

        try:
            # List all calendars
            calendar_list = service.calendarList().list().execute()
            calendars = calendar_list.get("items", [])

            for calendar in calendars:
                calendar_id = calendar.get("id", "")
                calendar_name = calendar.get("summary", calendar_id)

                logger.info(f"[{self.account}] Syncing calendar: {calendar_name}")

                cal_stats = self._sync_calendar(
                    calendar_id, calendar_name, time_min, time_max, existing_ids
                )

                stats["calendars"][calendar_name] = cal_stats
                stats["calendars_synced"] += 1
                stats["new_events"] += cal_stats["new"]
                stats["skipped"] += cal_stats["skipped"]
                stats["errors"] += cal_stats["errors"]

        except Exception as e:
            logger.error(f"Calendar sync error for account '{self.account}': {e}")
            stats["error_message"] = str(e)

        # Save sync state
        state["last_sync"] = datetime.utcnow().isoformat()
        state["last_stats"] = stats
        save_sync_state(state_file, state)

        logger.info(
            f"[{self.account}] Calendar sync complete: "
            f"{stats['new_events']} new, {stats['skipped']} skipped "
            f"from {stats['calendars_synced']} calendars"
        )

        return stats


def sync_calendar(
    account: str,
    lookback_days: int = 365,
    lookahead_days: int = 365,
) -> dict[str, Any]:
    """
    Convenience function to sync Calendar for an account.

    Args:
        account: Account name
        lookback_days: How many days back to sync
        lookahead_days: How many days forward to sync

    Returns:
        Sync statistics
    """
    syncer = CalendarSyncer(account, lookback_days, lookahead_days)
    return syncer.sync()
