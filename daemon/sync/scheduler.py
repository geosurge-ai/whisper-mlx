"""
Background scheduler for Google sync.

Runs Gmail and Calendar sync on a configurable interval.
Integrates with the daemon lifespan.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from .auth import is_authenticated
from .gmail import get_gmail_syncer
from .calendar import get_calendar_syncer
from .storage import get_storage_stats

logger = logging.getLogger("qwen.sync.scheduler")

# Default sync interval in seconds (5 minutes)
DEFAULT_SYNC_INTERVAL = 300

# Environment variable to configure sync interval
SYNC_INTERVAL_ENV = "QWEN_SYNC_INTERVAL"


def get_sync_interval() -> int:
    """Get sync interval from environment or default."""
    try:
        return int(os.environ.get(SYNC_INTERVAL_ENV, DEFAULT_SYNC_INTERVAL))
    except ValueError:
        return DEFAULT_SYNC_INTERVAL


class SyncScheduler:
    """Background scheduler for Google sync."""

    def __init__(self, interval_seconds: int | None = None):
        self.interval = interval_seconds or get_sync_interval()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._last_sync: datetime | None = None
        self._last_result: dict[str, Any] | None = None

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running

    @property
    def last_sync(self) -> datetime | None:
        """Get timestamp of last successful sync."""
        return self._last_sync

    @property
    def last_result(self) -> dict[str, Any] | None:
        """Get result of last sync."""
        return self._last_result

    def start(self) -> None:
        """Start the background sync scheduler."""
        if self._running:
            logger.warning("Sync scheduler already running")
            return

        if not is_authenticated():
            logger.warning(
                "Google not authenticated - sync scheduler disabled. "
                "Run: python -m daemon.sync.auth"
            )
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"📧 Sync scheduler started (interval: {self.interval}s)"
        )

    def stop(self) -> None:
        """Stop the background sync scheduler."""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

        logger.info("Sync scheduler stopped")

    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        # Run initial sync immediately
        await self._run_sync()

        while self._running:
            try:
                await asyncio.sleep(self.interval)
                if self._running:
                    await self._run_sync()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                # Continue running, will retry on next interval

    async def _run_sync(self) -> None:
        """Run a single sync cycle."""
        logger.info("Starting sync cycle...")
        start_time = datetime.now(timezone.utc)

        gmail_result: dict[str, Any] = {"error": None}
        calendar_result: dict[str, Any] = {"error": None}

        # Sync Gmail
        try:
            gmail_syncer = get_gmail_syncer()
            gmail_result = await gmail_syncer.sync()
        except Exception as e:
            logger.error(f"Gmail sync failed: {e}")
            gmail_result = {"error": str(e)}

        # Sync Calendar
        try:
            calendar_syncer = get_calendar_syncer()
            calendar_result = await calendar_syncer.sync()
        except Exception as e:
            logger.error(f"Calendar sync failed: {e}")
            calendar_result = {"error": str(e)}

        # Update state
        self._last_sync = datetime.now(timezone.utc)
        self._last_result = {
            "gmail": gmail_result,
            "calendar": calendar_result,
            "duration_seconds": (self._last_sync - start_time).total_seconds(),
            "storage": get_storage_stats(),
        }

        # Log summary
        duration = self._last_result["duration_seconds"]
        stats = self._last_result["storage"]
        logger.info(
            f"Sync cycle complete in {duration:.1f}s - "
            f"{stats['email_count']} emails, {stats['event_count']} events, "
            f"{stats['total_size_mb']}MB"
        )

    async def run_sync_now(self) -> dict[str, Any]:
        """Trigger an immediate sync (for manual use)."""
        await self._run_sync()
        return self._last_result or {}

    def get_status(self) -> dict[str, Any]:
        """Get current scheduler status."""
        return {
            "running": self._running,
            "interval_seconds": self.interval,
            "last_sync": self._last_sync.isoformat() if self._last_sync else None,
            "last_result": self._last_result,
            "authenticated": is_authenticated(),
        }


# Singleton instance
_scheduler: SyncScheduler | None = None


def get_scheduler() -> SyncScheduler:
    """Get the sync scheduler singleton."""
    global _scheduler
    if _scheduler is None:
        _scheduler = SyncScheduler()
    return _scheduler


def start_scheduler() -> None:
    """Start the background sync scheduler."""
    get_scheduler().start()


def stop_scheduler() -> None:
    """Stop the background sync scheduler."""
    scheduler = get_scheduler()
    if scheduler:
        scheduler.stop()
