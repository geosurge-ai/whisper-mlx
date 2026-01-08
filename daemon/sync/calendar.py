"""
Google Calendar sync module.

Fetches calendar events from Google Calendar API and stores them locally.
Supports incremental sync using sync tokens.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build

from .auth import get_google_credentials
from .storage import (
    get_sync_state,
    save_sync_state,
    save_calendar_event,
)

logger = logging.getLogger("qwen.sync.calendar")

# Default lookback/forward period for calendar sync
DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_FORWARD_DAYS = 365


class CalendarSyncer:
    """Syncs events from Google Calendar to local storage."""

    def __init__(
        self,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        forward_days: int = DEFAULT_FORWARD_DAYS,
    ):
        self.lookback_days = lookback_days
        self.forward_days = forward_days
        self._service = None

    def _get_service(self) -> Any:
        """Get or create Calendar API service."""
        if self._service is None:
            creds = get_google_credentials()
            if creds is None:
                raise RuntimeError(
                    "Not authenticated with Google. Run: python -m daemon.sync.auth"
                )
            self._service = build("calendar", "v3", credentials=creds)
        return self._service

    async def sync(self) -> dict[str, Any]:
        """
        Sync events from all calendars.

        Returns dict with sync statistics.
        """
        logger.info("Starting Calendar sync...")

        service = self._get_service()
        state = get_sync_state("calendar")

        # Get list of calendars
        calendars = self._get_calendar_list(service)
        logger.info(f"Found {len(calendars)} calendars to sync")

        total_new = 0
        total_updated = 0

        for calendar in calendars:
            cal_id = calendar["id"]
            cal_name = calendar.get("summary", cal_id)

            try:
                result = await self._sync_calendar(service, state, cal_id, cal_name)
                total_new += result["new"]
                total_updated += result["updated"]
            except Exception as e:
                logger.warning(f"Failed to sync calendar '{cal_name}': {e}")

        # Save state
        save_sync_state("calendar", state)

        logger.info(
            f"Calendar sync complete: {total_new} new, {total_updated} updated"
        )

        return {
            "calendars_synced": len(calendars),
            "new_events": total_new,
            "updated_events": total_updated,
        }

    def _get_calendar_list(self, service: Any) -> list[dict[str, Any]]:
        """Get list of all calendars."""
        calendars: list[dict[str, Any]] = []
        page_token = None

        while True:
            result = (
                service.calendarList()
                .list(pageToken=page_token)
                .execute()
            )

            calendars.extend(result.get("items", []))

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        return calendars

    async def _sync_calendar(
        self,
        service: Any,
        state: dict[str, Any],
        calendar_id: str,
        calendar_name: str,
    ) -> dict[str, Any]:
        """
        Sync a single calendar.

        Uses incremental sync if sync token is available.
        """
        sync_tokens = state.get("sync_tokens", {})
        sync_token = sync_tokens.get(calendar_id)

        if sync_token:
            # Incremental sync
            try:
                result = await self._incremental_sync_calendar(
                    service, calendar_id, calendar_name, sync_token
                )
                sync_tokens[calendar_id] = result["sync_token"]
                state["sync_tokens"] = sync_tokens
                return result
            except Exception as e:
                # Sync token expired or invalid
                if "410" in str(e) or "invalid" in str(e).lower():
                    logger.warning(
                        f"Sync token expired for '{calendar_name}', doing full sync"
                    )
                    sync_token = None
                else:
                    raise

        # Full sync
        result = await self._full_sync_calendar(service, calendar_id, calendar_name)
        sync_tokens[calendar_id] = result["sync_token"]
        state["sync_tokens"] = sync_tokens
        state["event_count"] = state.get("event_count", 0) + result["new"]
        return result

    async def _full_sync_calendar(
        self,
        service: Any,
        calendar_id: str,
        calendar_name: str,
    ) -> dict[str, Any]:
        """Perform full sync of a calendar."""
        logger.info(f"Full sync of calendar '{calendar_name}'...")

        # Calculate time range
        now = datetime.now(timezone.utc)
        time_min = (now - timedelta(days=self.lookback_days)).isoformat()
        time_max = (now + timedelta(days=self.forward_days)).isoformat()

        new_events = 0
        page_token = None
        sync_token = None

        while True:
            result = (
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

            events = result.get("items", [])

            for event in events:
                try:
                    self._store_event(event, calendar_id, calendar_name)
                    new_events += 1
                except Exception as e:
                    logger.warning(f"Failed to store event: {e}")

            # Get sync token from last page
            if "nextSyncToken" in result:
                sync_token = result["nextSyncToken"]

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        logger.info(f"Synced {new_events} events from '{calendar_name}'")

        return {
            "new": new_events,
            "updated": 0,
            "sync_token": sync_token,
        }

    async def _incremental_sync_calendar(
        self,
        service: Any,
        calendar_id: str,
        calendar_name: str,
        sync_token: str,
    ) -> dict[str, Any]:
        """Perform incremental sync using sync token."""
        logger.debug(f"Incremental sync of calendar '{calendar_name}'...")

        new_events = 0
        updated_events = 0
        page_token = None
        new_sync_token = sync_token

        while True:
            result = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    syncToken=sync_token if not page_token else None,
                    pageToken=page_token,
                    maxResults=250,
                )
                .execute()
            )

            events = result.get("items", [])

            for event in events:
                if event.get("status") == "cancelled":
                    # Event was deleted - we could remove it, but keeping for now
                    continue

                try:
                    self._store_event(event, calendar_id, calendar_name)
                    # Count as new or updated based on whether file exists
                    # For simplicity, counting all as updated in incremental
                    updated_events += 1
                except Exception as e:
                    logger.warning(f"Failed to store event: {e}")

            # Get sync token from last page
            if "nextSyncToken" in result:
                new_sync_token = result["nextSyncToken"]

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        if updated_events > 0:
            logger.info(f"Updated {updated_events} events from '{calendar_name}'")

        return {
            "new": new_events,
            "updated": updated_events,
            "sync_token": new_sync_token,
        }

    def _store_event(
        self,
        event: dict[str, Any],
        calendar_id: str,
        calendar_name: str,
    ) -> None:
        """Parse and store a calendar event."""
        # Extract start/end times
        start = event.get("start", {})
        end = event.get("end", {})

        # Handle all-day events vs timed events
        start_time = start.get("dateTime") or start.get("date")
        end_time = end.get("dateTime") or end.get("date")
        is_all_day = "date" in start and "dateTime" not in start

        # Extract attendees
        attendees = [
            a.get("email", "") for a in event.get("attendees", []) if a.get("email")
        ]

        # Check if recurring
        is_recurring = "recurringEventId" in event

        # Build event data
        event_data: dict[str, Any] = {
            "id": event["id"],
            "calendar_id": calendar_id,
            "calendar_name": calendar_name,
            "summary": event.get("summary", "(No title)"),
            "description": event.get("description", ""),
            "start": start_time,
            "end": end_time,
            "is_all_day": is_all_day,
            "location": event.get("location", ""),
            "attendees": attendees,
            "organizer": event.get("organizer", {}).get("email", ""),
            "status": event.get("status", ""),
            "recurring": is_recurring,
            "recurring_event_id": event.get("recurringEventId"),
            "html_link": event.get("htmlLink", ""),
            "created": event.get("created"),
            "updated": event.get("updated"),
        }

        save_calendar_event(event_data)


# Singleton instance
_calendar_syncer: CalendarSyncer | None = None


def get_calendar_syncer() -> CalendarSyncer:
    """Get the Calendar syncer singleton."""
    global _calendar_syncer
    if _calendar_syncer is None:
        _calendar_syncer = CalendarSyncer()
    return _calendar_syncer
